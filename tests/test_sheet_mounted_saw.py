"""Mounted-body readings stay in their proved frame when printed."""

import re
from copy import deepcopy

import pytest
from test_mounted_saw_zero import normalized_zero, prove_zero
from test_procedure_boxes import table_rows

from prechips.rules.zero_recipe import rule
from prechips.sheet import _Traveler


def reject_face_remap(*args, **kwargs):
    raise AssertionError("A proved mounted-saw setting is already in the setup frame")


@pytest.mark.parametrize("display_units,scale", [("mm", 1), ("in", 25.4)])
def test_mounted_axis_prints_proved_setting_and_both_jogs(monkeypatch, display_units, scale):
    data, setup, mounted = normalized_zero(monkeypatch)
    touch = mounted["zero"]["touches"][0]
    touch.update(kind="axis", position=0)
    touch.pop("before_ops")
    setup["ops"] = [setup["ops"][-1]]
    setup["zero"]["z"].update(
        tool="blade",
        holder="holder",
        method="mounted_saw_side",
        mounted_saw=deepcopy(touch["mounted_saw"]),
        check_jog_mm=5,
    )
    setup["zero"]["tool_touches"] = []
    data.plan["dro"]["units"] = display_units
    prove_zero(data, mounted)
    finding = rule.evaluate(data)[0]
    traveler = _Traveler(data, [finding], {}, None)
    monkeypatch.setattr(traveler, "datum_z", reject_face_remap)

    rows = table_rows(traveler.dro(setup, {}))
    [z] = [row for row in rows if row[0] == "Z"]
    assert float(z[2]) == pytest.approx(11.575 / scale, abs=0.0001)
    assert float(z[4]) == pytest.approx(16.575 / scale, abs=0.0001)
    assert float(z[5]) == pytest.approx(6.575 / scale, abs=0.0001)


def test_reinstalled_saw_tool_touch_keeps_its_proved_midplane(monkeypatch):
    data, setup, mounted = normalized_zero(monkeypatch)
    prove_zero(data, mounted)
    finding = rule.evaluate(data)[0]
    [touch] = finding.numbers["tool_touches"]
    traveler = _Traveler(data, [finding], {}, None)
    monkeypatch.setattr(traveler, "datum_z", reject_face_remap)

    text = traveler.tool_touch(setup, touch, {}, "spindle")
    setting = re.search(r"Axis Set Z\s+(-?\d+(?:\.\d+)?)", text)
    assert setting is not None
    assert float(setting.group(1)) == pytest.approx(11.575)
