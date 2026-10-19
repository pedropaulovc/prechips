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
from test_cli import SYNTHETIC_KERNEL, run_cli

from prechips.inputs import Bundle
from prechips.rules import op_chain, tool_resolves


def check(tmp_path, inventory, *, setup=""):
    for name, text in (
        ("features.toml", FEATURES),
        ("inventory.toml", inventory),
        ("cutting.toml", CUTTING),
        ("policy.toml", POLICY),
        ("plan.toml", HEADER + one_setup(face(), spot(), drill())),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    result = run_cli("check", tmp_path / "plan.toml", "--out", out, setup=setup)
    assert result.returncode in {0, 2, 4}, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    return result.returncode, {(f["rule"], f["subject"]): f for f in report["findings"]}


@pytest.mark.parametrize(
    "shank,status,expected_mm", [("3/8", "pass", 9.525), ("13/32", "error", 10.31875)]
)
def test_inch_shank_in_mm_collet_compares_physical_size(tmp_path, shank, status, expected_mm):
    # Exercise the real assembly consumer without unrelated rules or native geometry.
    bundle = Bundle(
        features={},
        plan={
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "ops": [{"op": 10, "do": "face", "tool": "endmill", "holder": "collet"}],
                }
            ]
        },
        inventory={
            "machines": {"mill": {"kind": "mill", "spindle": {"taper": "R8"}, "verify": False}},
            "tools": {"endmill": {"kind": "endmill", "shank_in": shank, "verify": False}},
            "holders": {
                "collet": {"kind": "collet", "taper": "R8", "capacity_mm": 9.525, "verify": False}
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )
    finding = next(row for row in tool_resolves.evaluate(bundle) if row.subject == "S1:10")
    assert finding.status == status
    assert finding.numbers["shank_mm"] == pytest.approx(expected_mm)
    assert finding.numbers["holder_capacity_mm"] == 9.525


def assembly(tmp_path, shank, capacity_mm):
    """The ``S1:10`` assembly finding for one tool shank fact in one nominal collet."""
    bundle = Bundle(
        features={},
        plan={
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "ops": [{"op": 10, "do": "face", "tool": "endmill", "holder": "collet"}],
                }
            ]
        },
        inventory={
            "machines": {"mill": {"kind": "mill", "spindle": {"taper": "R8"}, "verify": False}},
            "tools": {"endmill": {"kind": "endmill", **shank, "verify": False}},
            "holders": {
                "collet": {
                    "kind": "collet",
                    "taper": "R8",
                    "capacity_mm": capacity_mm,
                    "verify": False,
                }
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )
    return next(row for row in tool_resolves.evaluate(bundle) if row.subject == "S1:10")


@pytest.mark.parametrize(
    "shank,capacity_mm,status,band",
    [
        # 3/8 in: IT6 for above 6 up to and including 10 mm is 9 µm (ISO 286-1 Table 1).
        ({"shank_in": 0.3748}, 9.525, "pass", [9.516, 9.525]),
        ({"shank_in": 0.3752}, 9.525, "error", [9.516, 9.525]),
        ({"shank_in": 0.3745}, 9.525, "error", [9.516, 9.525]),
        ({"shank_mm": 9.995}, 10.0, "pass", [9.991, 10.0]),
        ({"shank_mm": 9.99}, 10.0, "error", [9.991, 10.0]),
        # Above 10 up to and including 18 mm: 11 µm; the lower limit itself fits.
        ({"shank_mm": 11.989}, 12.0, "pass", [11.989, 12.0]),
        ({"shank_mm": 11.988}, 12.0, "error", [11.989, 12.0]),
    ],
)
def test_nominal_collet_accepts_an_iso_286_h6_shank_band(
    tmp_path, shank, capacity_mm, status, band
):
    finding = assembly(tmp_path, shank, capacity_mm)
    assert finding.status == status
    assert finding.numbers["shank_fit"] == "ISO 286 h6"
    assert finding.numbers["shank_band_mm"] == pytest.approx(band)
    assert "ISO 286-1:2010 Table 1 IT6" in finding.cite
    if status == "error":
        assert finding.sentence == "S1:10: tool shank does not match selected collet."
    else:
        assert finding.sentence == "S1:10: holder interface and shank fit."


def test_nominal_shank_finding_is_unchanged_by_the_band(tmp_path):
    finding = assembly(tmp_path, {"shank_in": "3/8"}, 9.525)
    assert (finding.status, finding.sentence) == ("pass", "S1:10: holder interface and shank fit.")
    assert finding.numbers == {
        "tool": "endmill",
        "holder": "collet",
        "machine": "mill",
        "machine_standard": "R8",
        "holder_standard": "R8",
        "shank_mm": pytest.approx(9.525),
        "holder_capacity_mm": 9.525,
    }
    assert finding.cite == ["inventory spindle/holder/shank fields", "PLAN.md §4.1"]


@pytest.mark.parametrize("shank_mm,status", [(599.99, "unknown"), (600.01, "error")])
def test_nominal_collet_beyond_iso_286_table_never_passes_an_undersize_shank(
    tmp_path, shank_mm, status
):
    finding = assembly(tmp_path, {"shank_mm": shank_mm}, 600.0)
    assert finding.status == status
    assert finding.numbers["shank_band_mm"] == "unknown"
    if status == "unknown":
        assert "no IT6 above 500 mm" in finding.sentence


def test_mismatched_inch_shank_reaches_cli_report_and_stop(tmp_path):
    inventory = INVENTORY.replace(
        "shank_mm = 10.0\nflutes = 4", 'shank_in = "13/32"\nflutes = 4', 1
    ).replace("capacity_mm = 10.0", "capacity_mm = 9.525")
    code, findings = check(tmp_path, inventory, setup=SYNTHETIC_KERNEL)
    assert findings[("tool_resolves", "S1:10")]["status"] == "error"
    assert findings[("tool_resolves", "S1:10")]["numbers"]["shank_mm"] == pytest.approx(10.31875)
    assert code == 2


@pytest.mark.parametrize("drill_in,status", [("3/8", "pass"), ("13/32", "error")])
def test_inch_tap_drill_matches_equivalent_mm_specification(tmp_path, drill_in, status):
    bundle = Bundle(
        features={
            "features": {
                "t1": {
                    "kind": "threaded_hole",
                    "thread": "7/16-14",
                    "thread_hand": "right",
                    "thread_class": "2B",
                    "tap_drill_mm": 9.525,
                }
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
        inventory={
            "tools": {
                "drill": {"kind": "drill", "dia_in": drill_in, "verify": False},
                "tap": {
                    "kind": "tap",
                    "thread": "7/16-14",
                    "thread_hand": "right",
                    "thread_class": "2B",
                },
            }
        },
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
