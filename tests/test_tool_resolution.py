"""Inventory resolution boundaries: converted inch/mm lengths and schema-legal set shapes."""

import json

import pytest
from test_arithmetic import (
    CUTTING,
    FEATURES,
    HEADER,
    INVENTORY,
    POLICY,
    drill,
    face,
    one_setup,
    spot,
)
from test_cli import run_cli

from prechips.inputs import Bundle
from prechips.rules import op_chain


def check(tmp_path, inventory):
    for name, text in (
        ("features.toml", FEATURES),
        ("inventory.toml", inventory),
        ("cutting.toml", CUTTING),
        ("policy.toml", POLICY),
        ("plan.toml", HEADER + one_setup(face(), spot(), drill())),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    result = run_cli("check", tmp_path / "plan.toml", "--out", out)
    assert result.returncode in {0, 2, 4}, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    return result.returncode, {(f["rule"], f["subject"]): f for f in report["findings"]}


@pytest.mark.parametrize(
    "shank,status,code",
    [('shank_in = "3/8"', "pass", 0), ('shank_in = "13/32"', "error", 2)],
)
def test_inch_shank_in_mm_collet_compares_physical_size(tmp_path, request, shank, status, code):
    if code == 0:
        request.getfixturevalue("freecad_kernel")
    # 3/8 in converts to 9.524999999999999 mm; it is the 9.525 mm collet, 13/32 is not.
    inventory = INVENTORY.replace("shank_mm = 10.0\nflutes = 4", shank + "\nflutes = 4", 1)
    inventory = inventory.replace("capacity_mm = 10.0", "capacity_mm = 9.525")
    result, findings = check(tmp_path, inventory)
    assert findings[("tool_resolves", "S1:10")]["status"] == status
    assert result == code


@pytest.mark.parametrize("drill_in,status", [("3/8", "pass"), ("13/32", "error")])
def test_inch_tap_drill_matches_equivalent_mm_specification(tmp_path, drill_in, status):
    bundle = Bundle(
        features={
            "features": {
                "t1": {"kind": "threaded_hole", "thread": "7/16-14", "tap_drill_mm": 9.525}
            }
        },
        plan={
            "setups": [
                {
                    "id": "S1",
                    "ops": [
                        {"op": 10, "do": "spot", "feature": "t1", "tool": "spot"},
                        {"op": 20, "do": "drill", "feature": "t1", "tool": "drill"},
                        {"op": 30, "do": "tap", "feature": "t1", "tool": "tap"},
                    ],
                }
            ]
        },
        inventory={"tools": {"drill": {"kind": "drill", "dia_in": drill_in, "verify": False}}},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )
    [finding] = op_chain.evaluate(bundle)
    assert finding.status == status


@pytest.mark.parametrize(
    "shape,expected",
    [
        (
            'sizes_in = ["1/4", 0.375]\nflutes = [2, 4]\n',
            ["1-4in-2fl", "1-4in-4fl", "3-8in-2fl", "3-8in-4fl"],
        ),
        ('sizes_in = ["1/4", 0.375]\nflutes = 4\n', ["1-4in-4fl", "3-8in-4fl"]),
        (
            'flutes = 2\n[tools.ems.sizes_in]\nshort = ["1/4"]\nlong = ["3/8"]\n',
            ["1-4in-2fl", "3-8in-2fl"],
        ),
    ],
)
def test_endmill_set_shapes_enumerate_and_resolve_declared_members(tmp_path, shape, expected):
    path = tmp_path / "inventory.toml"
    path.write_text('[tools.ems]\nkind = "endmill_set"\nverify = false\n' + shape, "utf-8")
    result = run_cli("--json", "tools", "9.525", "--inventory", path)
    assert result.returncode == 0, result.stderr
    rows = {row["id"]: row for row in json.loads(result.stdout)}
    assert sorted(rows) == ["ems"] + [f"ems/{member}" for member in expected]
    for member in expected:
        row = rows[f"ems/{member}"]
        assert row["flutes"] == int(member.split("-")[-1].removesuffix("fl"))
        assert row["sizing"] == ("pass" if member.startswith("3-8in") else "error")


def test_grouped_collet_sizes_are_members_not_group_names(tmp_path):
    path = tmp_path / "inventory.toml"
    path.write_text(
        '[holders.collets]\nkind = "collet_set"\nverify = false\n'
        '[holders.collets.sizes_in]\nimperial = ["1/4", "0.375"]\n',
        "utf-8",
    )
    result = run_cli("--json", "tools", "--inventory", path)
    assert result.returncode == 0, result.stderr
    rows = {row["id"]: row for row in json.loads(result.stdout)}
    assert sorted(rows) == ["collets", "collets/0.375in", "collets/1-4in"]
    assert rows["collets/0.375in"]["size_mm"] == pytest.approx(9.525)
