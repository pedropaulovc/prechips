"""The shared milling force bound (docs/design/area-hold.md §4, #295 phase 2, #158) on
synthetic bundles: hand-computed cases, one perturbation per input, scope and entry."""

import copy
import math
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from prechips.model import CuttingData, Inventory, Operation
from prechips.rules._cutting_force import entry_of, milling_force

ROW_CITE = "scratch Kienzle fixture: synthetic kc1/mc/k_r, not a material recommendation"
CUT_CITE = "scratch chip-load fixture: synthetic fz"
HELIX = {"value": 30.0, "cite": "scratch vendor nominal"}


def bundle(tool=None, op=None, material=None, stock=None):
    """The section 10 worked example: D 9.525, z 4, β 30°, fz 0.05, kc1 1500, mc 0.25,
    k_r 0.4, ap 0.25, ae not declared (bound D)."""
    tool_record = {
        "kind": "endmill",
        "dia_mm": 9.525,
        "flutes": 4,
        "material": "hss",
        "helix_deg": copy.deepcopy(HELIX),
        "helix_hand": "right",
        "hand": "right",
        "verify": False,
    }
    tool_record.update(tool or {})
    op_record = {"op": 10, "do": "finish_face", "tool": "em", "doc_mm": 0.25}
    op_record.update(op or {})
    row = {
        "material_class": "steel",
        "kc1_n_per_mm2": 1500.0,
        "mc": 0.25,
        "radial_ratio": 0.4,
        "cite": ROW_CITE,
    }
    row.update(material or {})
    stock_record = {"material": "1018", "material_verify": False}
    stock_record.update(stock or {})
    return SimpleNamespace(
        plan={"stock": stock_record, "setups": [{"id": "S1", "ops": [op_record]}]},
        features={},
        inventory={"tools": {"em": tool_record}},
        cutting_data={
            "aliases": {"1018": "steel"},
            "cut": [
                {
                    "material_class": "steel",
                    "tool_material": "hss",
                    "operation": "face",
                    "diameter_range": [6.0, 12.0],
                    "sfm": 80.0,
                    "chip_load_mm_per_tooth": 0.05,
                    "cite": CUT_CITE,
                },
                {
                    "material_class": "steel",
                    "tool_material": "hss",
                    "operation": "profile",
                    "diameter_range": [6.0, 12.0],
                    "sfm": 80.0,
                    "chip_load_mm_per_tooth": 0.05,
                    "cite": CUT_CITE,
                },
            ],
            "material": [row],
        },
    )


def force(data, entry="side"):
    return milling_force(data, data.plan["setups"][0]["ops"][0], entry)


def kienzle(n_e, kc1, ap, h_max, mc):
    return n_e * kc1 * ap * h_max ** (1 - mc)


# --- hand-computed cases -----------------------------------------------------------------


def test_worked_example_matches_the_design_arithmetic():
    result = force(bundle())
    assert result.status == "computed"
    assert result.inputs["n_e"] == 2
    assert result.inputs["ae_basis"] == "bound_full_slot"
    assert result.inputs["tangential_n"] == pytest.approx(79.3, abs=0.1)
    assert result.lateral_n == pytest.approx(85.4, abs=0.1)
    assert result.axial_n == pytest.approx(45.8, abs=0.1)
    assert result.axial_sense == "lift"
    assert ROW_CITE in result.cite and CUT_CITE in result.cite and HELIX["cite"] in result.cite


def test_a_narrow_cut_takes_the_chip_at_its_exit_angle():
    # ae < D/2: φ_e < π/2, h_max = fz·sin φ_e.
    result = force(bundle(op={"ae_mm": 1.0}))
    phi = math.acos(1 - 2 * 1.0 / 9.525)
    assert result.inputs["ae_basis"] == "op_ae_mm"
    assert result.inputs["h_max_mm"] == pytest.approx(0.05 * math.sin(phi))
    assert result.inputs["n_e"] == math.ceil(4 * phi / (2 * math.pi))
    expected = kienzle(result.inputs["n_e"], 1500, 0.25, 0.05 * math.sin(phi), 0.25)
    assert result.inputs["tangential_n"] == pytest.approx(expected)


@pytest.mark.parametrize("flutes,n_e", [(2, 1), (3, 2), (4, 2)])
def test_full_slot_engages_half_the_flutes_rounded_up(flutes, n_e):
    result = force(bundle(tool={"flutes": flutes}))
    assert result.inputs["n_e"] == n_e
    assert result.inputs["tangential_n"] == pytest.approx(kienzle(n_e, 1500, 0.25, 0.05, 0.25))


def test_a_tooth_count_on_an_integer_boundary_is_not_rounded_up_by_float_residue():
    # z = 6 at φ_e = 120° (ae/D = 0.75, cos 240° = cos 120°) is exactly two teeth.
    diameter = 9.525
    ae = diameter * (1 - math.cos(4 * math.pi / 3)) / 2
    assert ae <= diameter
    naive = 6 * math.acos(1 - 2 * ae / diameter) / (2 * math.pi)
    assert math.ceil(naive) == 3  # the float residue this guards against
    result = force(bundle(tool={"flutes": 6}, op={"ae_mm": ae}))
    assert result.inputs["n_e"] == 2


def test_a_zero_helix_has_no_axial_force():
    result = force(bundle(tool={"helix_deg": {"value": 0.0, "cite": "straight flute"}}))
    assert result.status == "computed"
    assert result.axial_n == 0.0


@pytest.mark.parametrize(
    "helix_hand,hand,sense",
    [
        ("right", "right", "lift"),
        ("left", "left", "lift"),
        ("right", "left", "push"),
        ("left", "right", "push"),
        ("unknown", "right", "lift"),
        ("right", "unknown", "lift"),
    ],
)
def test_axial_sense_by_helix_and_cutting_hand(helix_hand, hand, sense):
    result = force(bundle(tool={"helix_hand": helix_hand, "hand": hand}))
    assert result.axial_sense == sense
    assert result.inputs["helix_hand"] == helix_hand
    assert result.inputs["hand"] == hand


def test_step_over_is_never_read_as_the_width_of_cut():
    result = force(bundle(op={"contour": {"step_mm": 1.0}}))
    assert result.inputs["ae_basis"] == "bound_full_slot"
    assert result.inputs["ae_mm"] == 9.525


# --- one perturbation per input (#289) --------------------------------------------------


@pytest.mark.parametrize(
    "parts,name",
    [
        ({"tool": {"verify": True}}, "tool"),
        ({"tool": {"dia_mm": "unknown"}}, "D"),
        ({"tool": {"dia_mm": {"value": 9.525, "verify": True}}}, "D"),
        ({"tool": {"flutes": "unknown"}}, "z"),
        ({"tool": {"flutes": 0}}, "z"),
        ({"tool": {"flutes": [2, 4]}}, "z"),
        ({"tool": {"helix_deg": "unknown"}}, "helix_deg"),
        ({"tool": {"helix_deg": 30.0}}, "helix_deg"),  # bare: no source
        ({"tool": {"helix_deg": {"value": 30.0}}}, "helix_deg"),
        ({"tool": {"helix_deg": {**HELIX, "verify": True}}}, "helix_deg"),
        ({"tool": {"helix_deg": {"value": -30.0, "cite": "x"}}}, "helix_deg"),
        ({"tool": {"helix_deg": {"value": 90.0, "cite": "x"}}}, "helix_deg"),
        ({"tool": {"material": "carbide"}}, "fz"),
        ({"op": {"doc_mm": "unknown"}}, "ap"),
        ({"op": {"doc_mm": 0}}, "ap"),
        ({"op": {"ae_mm": 0}}, "ae"),
        ({"op": {"ae_mm": 10.0}}, "ae"),
        ({"material": {"kc1_n_per_mm2": "unknown"}}, "kc1_n_per_mm2"),
        ({"material": {"kc1_n_per_mm2": 0}}, "kc1_n_per_mm2"),
        ({"material": {"mc": 1.0}}, "mc"),
        ({"material": {"mc": -0.1}}, "mc"),
        ({"material": {"radial_ratio": "unknown"}}, "radial_ratio"),
        ({"material": {"radial_ratio": -0.1}}, "radial_ratio"),
        ({"material": {"cite": "unknown"}}, "material"),
        ({"material": {"verify": True}}, "material"),
        ({"material": {"material_class": "brass"}}, "material"),
        ({"stock": {"material_verify": True}}, "material"),
        ({"stock": {"material": "mystery"}}, "material"),
    ],
)
def test_each_missing_or_out_of_domain_input_is_unknown_naming_it(parts, name):
    result = force(bundle(**parts))
    assert result.status == "unknown"
    assert result.lateral_n == "unknown" and result.axial_n == "unknown"
    named = [debt.split(":")[0] for debt in result.debts]
    assert name in named
    # Only its own consumers follow: an unknown tool field leaves the tool unverified, and
    # fz is selected by the tool diameter and the stock's material class.
    assert set(named) <= {name, "tool", "fz"}


def test_every_debt_is_reported_not_only_the_first():
    result = force(bundle(tool={"flutes": 0}, op={"doc_mm": 0}, material={"mc": 2.0}))
    assert [debt.split(":")[0] for debt in result.debts] == ["z", "ap", "mc"]


def test_a_cited_chart_on_the_tool_supplies_fz():
    chart = {"chart": "scratch tool chart", "chip_load_mm_per_tooth": 0.02, "material": "x"}
    result = force(bundle(tool=chart))
    assert result.status == "computed"
    assert result.inputs["fz_mm"] == 0.02
    assert "scratch tool chart" in result.cite


# --- scope and entry -------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["drill", "spot_drill", "reamer", "tap"])
def test_drill_family_tools_have_no_thrust_torque_model(kind):
    result = force(bundle(tool={"kind": kind}, op={"do": "drill"}))
    assert result.status == "unknown"
    assert result.debts == [f"tool: no thrust/torque force model for {kind}"]


@pytest.mark.parametrize("action", ["fit", "inspect", "release"])
def test_noncutting_actions_are_not_applicable(action):
    assert force(bundle(op={"do": action})).status == "not_applicable"


def test_an_end_mill_counterbore_cuts_with_its_end():
    result = force(bundle(op={"do": "counterbore"}))
    assert result.status == "unknown"
    assert result.debts[0].startswith("entry: no axial-entry force model")


@pytest.mark.parametrize(
    "parts,reason",
    [
        ({"op": {"do": "unknown"}}, "operation: the op's action is unknown"),
        ({"op": {"do": "finish_turn"}}, "operation: no force model for finish_turn"),
        ({"tool": {"kind": "boring_head"}}, "tool: no force model for tool kind boring_head"),
        ({"tool": {"kind": "unknown"}}, "tool: no force model for tool kind unknown"),
    ],
)
def test_other_cutting_ops_stay_unknown(parts, reason):
    result = force(bundle(**parts))
    assert result.status == "unknown"
    assert result.debts == [reason]


@pytest.mark.parametrize(
    "entry,why", [("plunge", "its path plunges"), ("unknown", "its entry is unproven")]
)
def test_only_a_side_entry_is_computed(entry, why):
    result = force(bundle(), entry)
    assert result.status == "unknown"
    assert result.debts == [f"entry: no axial-entry force model ({why})"]


@pytest.mark.parametrize(
    "path,entry",
    [
        (None, "unknown"),
        ({"entries": []}, "unknown"),
        ({"entries": [{"air": True}, {"air": True}]}, "side"),
        ({"entries": [{"air": True}, {"air": False}]}, "plunge"),
        ({"entries": [{"air": False}], "lowered": "top"}, "side"),
    ],
)
def test_entry_comes_from_the_coordinates_level_path(path, entry):
    assert entry_of(path) == entry


# --- schema ----------------------------------------------------------------------------


def test_helix_fields_ae_and_kienzle_coefficients_load():
    Inventory.model_validate(
        {
            "tools": {
                "em": {
                    "kind": "endmill",
                    "helix_deg": {"value": 0.0, "cite": "straight flute"},
                    "helix_hand": "left",
                }
            }
        }
    )
    Operation.model_validate({"op": 10, "do": "finish_face", "ae_mm": 2.0})
    CuttingData.model_validate(
        {
            "material": [
                {"material_class": "steel", "kc1_n_per_mm2": 1500, "mc": 0.25, "radial_ratio": 0.4}
            ]
        }
    )


@pytest.mark.parametrize(
    "tool",
    [
        {"helix_hand": "cw"},
        {"helix_deg": {"value": 30.0, "cite": "x", "sign": -1}},
    ],
)
def test_malformed_helix_fields_are_bad_input(tool):
    with pytest.raises(ValidationError):
        Inventory.model_validate({"tools": {"em": {"kind": "endmill", **tool}}})
