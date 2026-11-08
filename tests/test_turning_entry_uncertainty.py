"""Bounded single-point entry is uncertainty, never credited stock or blanket clearance.

These real-FreeCAD jobs use cylinders and deliberately separated obstacle witnesses:
raw outside the entry, protected source inside the nose, head beyond the cutting
edges, holder beyond the head, and material beyond the opposite window end. No
assertion depends on diagnostic prose or on a production collision helper's answer.
"""

import math
import subprocess

import pytest
from test_fixture_solids import UP, _box
from test_kernel_geometry import Engine
from test_turning_geometry import _bar, _lathe, _turn

_RADIUS = 4.0
_NOSE = 0.4
_LENGTH = 40.0
_ENTRY = 30.0
_STOP = -0.6

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
plain = Part.makeCylinder(4, 40)
# The boss starts beyond the command's z=30 entry. It cannot be removed by
# the in-window cut, but contains the nose centre (r=4.4, z=30.4).
boss = plain.fuse(Part.makeCylinder(5, 1, V(0, 0, 30.2))).removeSplitter()
for name, shape in (("plain", plain), ("boss", boss)):
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")
"""


@pytest.fixture(scope="module")
def entry_solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("turn-entry-uncertainty")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {name: directory / f"{name}.step" for name in ("plain", "boss")}
    assert all(path.exists() for path in paths.values()), process.stdout + process.stderr
    return paths


def _placed_box(name=None, at=None, size=None):
    """A stock-contacting central support, with an optional collision witness."""
    # The support's top touches the z=0 end face without entering the stock.
    # Its maximum radius sqrt(2) stays inside even the undersize r3.9 target,
    # so neither the tool nor its holder can meet it during either feed direction.
    # A remote witness alone is not valid holding: custom fixtures must bear
    # on the stock directly or through a bearing clamp.
    solids = [_box("core support", [-1.0, -1.0, -2.0], [2.0, 2.0, 2.0])]
    if name is not None:
        solids.append(_box(name, list(at), list(size)))
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": solids,
        "debts": [],
        "gaps": [],
    }


@pytest.fixture
def entry_turn(tmp_path, freecad_kernel, entry_solids):
    engine = Engine(tmp_path, freecad_kernel)

    def run(
        *,
        shape="plain",
        raw_radius=6.0,
        window=(_ENTRY, _STOP),
        explicit=True,
        hold=None,
        later=False,
        **changes,
    ):
        step = entry_solids[shape]
        before = step.read_bytes()
        # Claim only the lower journal on the bossed source. Its unselected boss
        # is independently protected, not an alternative claimed cutting profile.
        high = 30.2 if shape == "boss" else _LENGTH
        journal = engine.refs(
            step, (-_RADIUS, -_RADIUS, 0), (_RADIUS, _RADIUS, high), kind="Cylinder"
        )
        assert len(journal) == 1
        command = {"to_dia_mm": 2 * _RADIUS} if explicit else {}
        if window is not None:
            command.update(z_from=window[0], z_to=window[1])
        op = _turn("S1:10", "journal", **(command | changes))
        later_op = _turn("S1:20", "journal", z_from=_LENGTH, z_to=_STOP, to_dia_mm=8.0)
        downstream_op = {**later_op, "subject": "S2:10"}
        first = _lathe([op, later_op] if later else [op])
        first["hold"] = _placed_box() if hold is None else hold
        second = _lathe([downstream_op] if later else [], "S2")
        second["hold"] = _placed_box()
        result = engine.run(
            engine.job(
                step,
                {"journal": journal},
                [first, second],
                stock=_bar(length=_LENGTH, dia=2 * raw_radius),
            )
        )
        assert result["status"] != "error", result.get("reason")
        first_facts = result["setups"]["S1"]
        assert first_facts["fixture_rendered"] is True, {
            "fixture_reason": first_facts.get("fixture_reason"),
            "scene_debts": first_facts.get("render_scene", {}).get("debts"),
        }
        assert step.read_bytes() == before
        return result

    return run


def _held(result, *, entry=_ENTRY, window=(_ENTRY, _STOP), explicit=True, raw_radius=6.0):
    detail = result["ops"]["S1:10"]
    record = detail["turn_entry"]
    assert record["status"] == "unknown"
    assert record["entry_z_mm"] == pytest.approx(entry)
    assert record["z_mm"] == pytest.approx(sorted(window))
    assert isinstance(record["reason"], str) and record["reason"].strip()
    assert isinstance(detail["unsupported_reason"], str) and detail["unsupported_reason"].strip()
    attainment = detail["turn_target" if explicit else "turn_window"]
    assert attainment["status"] == attainment["attained_indices"] == "unknown"
    assert attainment["z_mm"] == pytest.approx(sorted(window))
    first, downstream = result["setups"]["S1"], result["setups"]["S2"]
    # The known arriving bar remains a fact, but neither a diagnostic entry
    # region nor the otherwise-derivable in-window cut becomes outgoing stock.
    assert first["stock_volume_mm3"] == pytest.approx(math.pi * raw_radius**2 * _LENGTH, abs=0.001)
    assert first["stock_out_reason"]
    assert "stock_out_volume_mm3" not in first
    assert "stock_out_bbox_mm" not in first
    assert downstream["stock_reason"]
    assert "stock_volume_mm3" not in downstream
    assert "stock_bbox_mm" not in downstream
    return detail


def _positive(detail, kind="tool"):
    value = detail["min_hits"][kind]
    assert type(value) is int and value > 0


@pytest.mark.parametrize("do", ["rough_turn", "finish_turn"])
@pytest.mark.parametrize("explicit", [False, True], ids=["cad_window", "explicit_target"])
def test_raw_entry_shoulder_holds_stock_attainment_and_later_operations(entry_turn, do, explicit):
    result = entry_turn(do=do, explicit=explicit, later=True)
    detail = _held(result, explicit=explicit)
    # A finite nose-centred disk lies in raw r4..6 above z30, but outside the
    # protected r4 source. The long head and holder start beyond this raw radius.
    assert detail["min_hits"]["tool"] == detail["tool_hits"] == "unknown"
    assert detail["min_hits"]["holder"] == 0
    for subject in ("S1:20", "S2:10"):
        later = result["ops"][subject]
        assert later["turn_target"]["status"] == "unknown"
        assert later["turn_target"]["attained_indices"] == "unknown"
        assert later["tool_hits"] == "unknown"
        assert later["reasons"]["tool_hits"]


def test_positive_feed_uses_the_low_physical_entry_not_the_high_window_end(entry_turn):
    window = (10.0, 40.6)
    result = entry_turn(window=window, feed_z=1)
    detail = _held(result, entry=10.0, window=window)
    assert detail["min_hits"]["tool"] == detail["tool_hits"] == "unknown"
    assert detail["min_hits"]["holder"] == 0


@pytest.mark.parametrize("do", ["rough_turn", "finish_turn"])
@pytest.mark.parametrize("explicit", [False, True], ids=["cad_window", "explicit_target"])
def test_free_entry_remains_accepted_and_known_clear(entry_turn, do, explicit):
    result = entry_turn(do=do, explicit=explicit, window=(_LENGTH, _STOP))
    detail = result["ops"]["S1:10"]
    assert "turn_entry" not in detail
    assert "unsupported_reason" not in detail
    attainment = detail["turn_target" if explicit else "turn_window"]
    assert attainment["status"] == "accepted"
    assert len(attainment["attained_indices"]) == 1
    assert detail["min_hits"] == {"tool": 0, "holder": 0}
    assert detail["tool_hits"] == detail["holder_hits"] == 0
    assert detail["obstacles"] == {"tool": [], "holder": []}
    first, downstream = result["setups"]["S1"], result["setups"]["S2"]
    assert "stock_out_reason" not in first
    assert "stock_reason" not in downstream
    # Stop -0.6 puts the entire R0.4 terminal blend below the source's z=0.
    expected = math.pi * _RADIUS**2 * _LENGTH
    assert first["stock_out_volume_mm3"] == pytest.approx(expected, abs=0.001)
    assert downstream["stock_volume_mm3"] == pytest.approx(expected, abs=0.001)


def test_unselected_protected_entry_boss_keeps_a_certain_tool_collision(entry_turn):
    detail = _held(entry_turn(shape="boss"))
    _positive(detail)
    assert "part" in detail["obstacles"]["tool"]
    start = next(pose for pose in detail["window_poses"] if pose["end"] == "z_from")
    assert "part" in start["meets"]
    # The r5 boss contains the R0.4 nose centre (4.4, 30.4), while the
    # surrounding r5..6 raw still supplies a separate entry uncertainty region.
    assert _RADIUS + _NOSE < 5.0
    assert 30.2 < _ENTRY + _NOSE < 31.2


def test_undersize_command_cannot_hide_protected_core_as_entry_uncertainty(entry_turn):
    result = entry_turn(to_dia_mm=7.8)
    detail = result["ops"]["S1:10"]
    _positive(detail)
    assert "part" in detail["obstacles"]["tool"]
    assert detail["turn_target"]["status"] == "unknown"
    assert detail["turn_target"]["attained_indices"] == "unknown"
    assert result["setups"]["S1"]["stock_out_reason"]
    assert "stock_out_volume_mm3" not in result["setups"]["S1"]
    assert result["setups"]["S2"]["stock_reason"]
    assert "stock_volume_mm3" not in result["setups"]["S2"]


def test_noncutting_head_outside_entry_is_not_downgraded_with_the_insert(entry_turn):
    raw_radius, edge, head = 12.0, 1.0, 15.0
    detail = _held(entry_turn(raw_radius=raw_radius, edge_len_mm=edge), raw_radius=raw_radius)
    # Independent meridian witness: (r8, z33) is inside the triangle joining
    # nose centre (4.4,30.4) to the head's front/back (19.4,32.4)/(19.4,42.4).
    # It is outside EVERY nose/edge point's radial bound, yet inside raw stock.
    cr, cz = _RADIUS + _NOSE, _ENTRY + _NOSE
    r, z = 8.0, 33.0
    assert cr + edge + _NOSE < r < raw_radius < cr + head
    fraction = (r - cr) / head
    assert cz + 2.0 * fraction < z < cz + 12.0 * fraction
    _positive(detail)
    assert "part" in detail["obstacles"]["tool"]
    assert detail["min_hits"]["holder"] == 0


def test_holder_only_placed_clash_keeps_its_positive_lower_bound(entry_turn):
    name = "holder witness"
    # At entry the shank is r19.4..29.4, z32.4..42.4. This box lies
    # wholly beyond the tool head's maximum r19.4, but inside that shank.
    fixture = _placed_box(name, (22.0, -1.0, 33.0), (2.0, 2.0, 2.0))
    detail = _held(entry_turn(hold=fixture))
    _positive(detail, "holder")
    assert name in detail["obstacles"]["holder"]
    assert name not in detail["obstacles"]["tool"]
    assert detail["min_hits"]["tool"] == "unknown"


def test_placed_fixture_inside_insert_keeps_a_certain_tool_collision(entry_turn):
    name = "insert witness"
    # At entry the 60-degree insert's trailing edge reaches about
    # (r9.39,z40.20). This box is inside the insert, outside the r6 bar,
    # and far inside the shank's starting radius. It is not entry raw.
    fixture = _placed_box(name, (8.0, -0.25, 35.0), (1.0, 0.5, 1.0))
    detail = _held(entry_turn(hold=fixture))
    _positive(detail)
    assert name in detail["obstacles"]["tool"]
    assert detail["min_hits"]["holder"] == 0
    start = next(pose for pose in detail["window_poses"] if pose["end"] == "z_from")
    assert name in start["meets"]


def test_holder_crossing_raw_beyond_entry_remains_a_certain_collision(entry_turn):
    raw_radius = 22.0
    detail = _held(entry_turn(raw_radius=raw_radius), raw_radius=raw_radius)
    # The entry shank spans r19.4..29.4 and z32.4..42.4. The independent
    # witness (r21,z35) is in raw r22 x40, outside the command ending at z30,
    # and beyond the entire cutting head. Entry uncertainty cannot mask it.
    assert _RADIUS + _NOSE + 15.0 < 21.0 < raw_radius
    assert _ENTRY + _NOSE + 2.0 < 35.0 < _LENGTH
    _positive(detail, "holder")
    assert "part" in detail["obstacles"]["holder"]


@pytest.mark.parametrize("entry", [_ENTRY, _LENGTH], ids=["held_entry", "free_entry"])
def test_true_opposite_side_terminal_collision_stays_positive(entry_turn, entry):
    window = (entry, 10.0)
    result = entry_turn(window=window, entering_angle_deg=60.0)
    detail = _held(result, window=window) if entry == _ENTRY else result["ops"]["S1:10"]
    if entry == _LENGTH:
        assert "turn_entry" not in detail
        assert detail["turn_target"]["status"] == "accepted"
    # The neutral leading edge slopes toward -Z, unlike the 93-degree tool.
    # A point 1 mm along it is at r5.266,z9.9: inside raw r6 below stop10,
    # outside protected r4, and on the OPPOSITE side from entry uncertainty.
    witness_r = _RADIUS + _NOSE + math.sin(math.radians(60.0))
    witness_z = 10.0 + _NOSE - math.cos(math.radians(60.0))
    assert _RADIUS < witness_r < 6.0 and witness_z < 10.0
    _positive(detail)
    assert "part" in detail["obstacles"]["tool"]
    terminal = next(pose for pose in detail["window_poses"] if pose["end"] == "z_to")
    assert "part" in terminal["meets"]


def test_unbounded_turn_keeps_existing_stock_and_known_clear_behavior(entry_turn):
    result = entry_turn(window=None, explicit=False)
    detail = result["ops"]["S1:10"]
    assert "turn_entry" not in detail
    assert "turn_window" not in detail
    assert "turn_target" not in detail
    assert "unsupported_reason" not in detail
    assert detail["min_hits"] == {"tool": 0, "holder": 0}
    assert detail["tool_hits"] == detail["holder_hits"] == 0
    assert "stock_out_reason" not in result["setups"]["S1"]
    assert "stock_reason" not in result["setups"]["S2"]
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(
        math.pi * _RADIUS**2 * _LENGTH, abs=0.001
    )
