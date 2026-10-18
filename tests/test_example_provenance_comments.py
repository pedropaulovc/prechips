"""Comment-only example provenance cannot certify a schema-capable shop fact."""

import copy
import tomllib

import pytest
from test_validate_examples import ROOT, VALIDATOR

INVENTORY = ROOT / "examples" / "inventory" / "pedro-shop.toml"
RECORD_ANCHORS = {
    ("gauges", name, "resolution_mm")
    for name in (
        "rocker-profile-template",
        "rocker-datum-indicator",
        "rocker-position-height-gauge",
        "rocker-position-pins",
        "rocker-position-blocks",
        "radius-gauge",
        "bracket-cross-bore-pins",
        "rocker-outline-template",
        "calipers-18in",
    )
} | {("tools", "rocker-rod-pilot-drill", "members", "1.85mm", "shank_mm")}
PLAIN_ANCHORS = {
    ("fixtures", "chuck-3jaw-6-d1-4", "range_mm"),
    ("fixtures", "chuck-4jaw-6-d1-4", "range_mm"),
    ("fixtures", "chuck-4jaw-5-bs0", "range_mm"),
    ("machines", "bandsaw-4x6", "blade_speed_sfm"),
    ("gauges", "bore-replica-kit", "ra_range"),
    ("gauges", "rocker-position-pins", "sizes_mm"),
    ("gauges", "rocker-position-blocks", "sizes_mm"),
    ("tools", "barrel-lap-acro-1-4", "range_mm"),
}


def test_worked_inventory_comment_provenance_scan_has_schema_and_plain_anchors():
    source = INVENTORY.read_text(encoding="utf-8")
    fields = list(VALIDATOR["inventory_provenance_fields"](source))
    supported = {path for path, _, _, _, capable in fields if capable}
    plain = {path for path, _, _, _, capable in fields if not capable}
    assert RECORD_ANCHORS <= supported, RECORD_ANCHORS - supported
    assert PLAIN_ANCHORS <= plain, PLAIN_ANCHORS - plain
    assert VALIDATOR["check_inventory_provenance"](source, str(INVENTORY)) == {
        "record_fields": supported,
        "plain_fields": plain,
    }


@pytest.mark.parametrize(
    "source",
    [
        "[gauges.indicator]\nresolution_mm = 0.001 # example: display step\n",
        '[gauges.indicator]\n# measured = { status = "illustrative" }\nresolution_mm = 0.001\n',
        "[gauges.indicator]\nresolution_in = 0.0001 # example: dial graduation\n",
        '[tools.drill.members."#47"]\nshank_mm = 1.85 # example: straight shank\n',
        '[tools.drill]\nshank_in = "3/8" # example: catalogue shank\n',
        '[tools.drill]\nnote = "illustrative example purchase"\n'
        '[tools.drill.members."#47"]\nshank_mm = 1.85\n',
        "[gauges.radius]\nresolution_mm = 0.1\n"
        'note = "Capability provenance: illustrative example"\n',
        "[gauges.indicator]\nresolution_mm = { value = 0.001 } # example\n",
        "[machines.mill.envelope.travel_mm]\nx = 500.0 # example\n",
        '[tools.drill.projection_mm]\n"holder/1-4in" = 30.0 # example\n',
    ],
)
def test_schema_capable_bare_fact_beside_provenance_is_rejected(source):
    fields = list(VALIDATOR["inventory_provenance_fields"](source))
    assert len(fields) == 1 and fields[0][-1] is True
    with pytest.raises(ValueError, match="fact-local measured record"):
        VALIDATOR["check_inventory_provenance"](source)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("range_mm", "[0.0, 300.0]"),
        ("range_in", "12.0"),
        ("ra_range", "[0.4, 6.3]"),
        ("sizes_mm", "[2.0, 2.01, 2.09]"),
        ("blade_speed_sfm", "[80.0, 200.0]"),
    ],
)
@pytest.mark.parametrize(
    "verification", ["", "verify = false\n", 'verify = "unknown"\n', "verify = true\n"]
)
def test_plain_example_nominal_requires_exact_disclosure_not_item_demotion(
    field, value, verification
):
    source = f"[gauges.example-item]\n{field} = {value} # illustrative example\n{verification}"
    fields = list(VALIDATOR["inventory_provenance_fields"](source))
    assert len(fields) == 1 and fields[0][-1] is False
    with pytest.raises(ValueError, match="exact source disclosure marker"):
        VALIDATOR["check_inventory_provenance"](source)
    result = VALIDATOR["check_inventory_provenance"](
        "[gauges.example-item]\n"
        "# source: example value (realistic, not a shop measurement); basis: local test nominal\n"
        f"{field} = {value}\n{verification}"
    )
    assert result == {
        "record_fields": set(),
        "plain_fields": {("gauges", "example-item", field)},
    }


def test_only_record_capable_fields_require_fact_local_provenance():
    source = (
        """[tools.drill.members."#47"]
# measured = { status = "illustrative", instrument = "visual flute count" }
flutes = 2
shank_mm = { value = 1.85, measured = { status = "illustrative","""
        """ by = "example (plausible, not measured)", date = "2026-10-05","""
        """ instrument = "micrometer on shank" } } # example
"""
    )
    result = VALIDATOR["check_inventory_provenance"](source)
    assert result == {
        "record_fields": {("tools", "drill", "members", "#47", "shank_mm")},
        "plain_fields": set(),
    }


def test_unmarked_catalogue_nominals_and_unknowns_are_not_relabelled():
    source = """# The file's example policy is not fact-local provenance.
[gauges.indicator]
resolution_mm = 0.001 # catalogue nominal
range_mm = [0.0, 0.8]
[gauges.unread]
resolution_mm = "unknown" # illustrative example lacks a value
"""
    assert VALIDATOR["check_inventory_provenance"](source) == {
        "record_fields": set(),
        "plain_fields": set(),
    }


@pytest.fixture(scope="module")
def worked_example_data():
    inventory = tomllib.loads(INVENTORY.read_text(encoding="utf-8"))
    filename = "cone-pivot-post/built-up.toml"
    plans = {filename: tomllib.loads((ROOT / "examples" / filename).read_text(encoding="utf-8"))}
    return inventory, plans


def test_bare_capability_disclosures_preserve_the_existing_nominal_contract():
    source = INVENTORY.read_text(encoding="utf-8")
    plain = [field for field in VALIDATOR["inventory_provenance_fields"](source) if not field[-1]]
    assert len(plain) == 34
    assert len({path[:2] for path, _, _, _, _ in plain}) == 30
    assert PLAIN_ANCHORS <= {path for path, _, _, _, _ in plain}
    for path, _, item, value, _ in plain:
        assert "verify" not in item, path
        assert not isinstance(value, dict), path
    VALIDATOR["check_inventory_provenance"](source)


def test_a_plain_capability_cannot_gain_a_fake_measured_wrapper():
    source = (
        """[gauges.example-item]
# source: example value (realistic, not a shop measurement); basis: synthetic nominal
range_mm = { value = 300.0, measured = { status = "measured","""
        """ by = "example value (realistic, not a shop measurement)","""
        """ date = "2026-10-11","""
        """ instrument = "example fixture (no physical measurement)" } }
"""
    )
    with pytest.raises(ValueError, match="example bare nominal"):
        VALIDATOR["check_inventory_provenance"](source)


def test_realistic_demo_scan_is_nonempty_anchored_and_has_two_selected_assumptions(
    worked_example_data,
):
    inventory, plans = worked_example_data
    found = VALIDATOR["check_example_measurements"](inventory, plans)
    assert len(found["demo"] - found["assumed"]) == 816
    assert len(found["real"]) == 6
    expected = {
        ("tools", "reamers-decimal", "members", "0.4500in", "lead_mm"): (
            "cone-pivot-post/built-up.toml",
            "S8",
            30,
            "blind_depth",
            "crank_bore",
        ),
        ("tools", "reamers-decimal", "members", "0.4835in", "lead_mm"): (
            "cone-pivot-post/built-up.toml",
            "S9",
            30,
            "blind_depth",
            "journal_bore",
        ),
    }
    assert found["assumed"] == expected.keys()
    assert found["consumers"] == expected
    assert ("machines", "PM-30MV", "resolution_mm") in found["demo"]
    assert ("gauges", "radius-gauge", "resolution_mm") in found["demo"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("by", "example (plausible, not measured)"),
        ("by", "example value (realistic, not a shop measurement) "),
        ("date", "2026-10-12"),
        ("instrument", "calipers"),
        ("status", "illustrative"),
        ("status", "assumed"),
        ("status", None),
    ],
)
def test_demo_markers_are_exact_and_cannot_hide_extra_assumed_grid_debt(
    worked_example_data, field, value
):
    original, plans = worked_example_data
    inventory = copy.deepcopy(original)
    fact = inventory["machines"]["PM-30MV"]["resolution_mm"]
    physical = fact["value"]
    if value is None:
        del fact["measured"][field]
    else:
        fact["measured"][field] = value
    assert fact["value"] == physical
    with pytest.raises(ValueError, match="exact measured marker"):
        VALIDATOR["check_example_measurements"](inventory, plans)


def test_demo_scan_rejects_losing_a_nonanchor_measurement(worked_example_data):
    original, plans = worked_example_data
    inventory = copy.deepcopy(original)
    del inventory["tools"]["reamers-decimal"]["members"]["0.4500in"]["oal_mm"]["measured"]
    with pytest.raises(ValueError, match="measurement count changed"):
        VALIDATOR["check_example_measurements"](inventory, plans)


@pytest.mark.parametrize("change", ["unselected", "extra_consumer", "other_plan", "promoted"])
def test_deliberate_assumptions_must_remain_local_and_actually_selected(
    worked_example_data, change
):
    original_inventory, original_plans = worked_example_data
    inventory, plans = copy.deepcopy((original_inventory, original_plans))
    setup = next(s for s in plans["cone-pivot-post/built-up.toml"]["setups"] if s["id"] == "S8")
    operation = next(op for op in setup["ops"] if op["op"] == 30)
    if change == "unselected":
        operation["tool"] = "unselected-reamer"
    elif change == "extra_consumer":
        setup["ops"].append({**operation, "op": 31})
    elif change == "other_plan":
        plans["extra-plan.toml"] = {"setups": [copy.deepcopy(setup)]}
    else:
        inventory["tools"]["reamers-decimal"]["members"]["0.4500in"]["lead_mm"]["measured"][
            "status"
        ] = "measured"
    with pytest.raises(ValueError, match="selected only|exact assumed marker"):
        VALIDATOR["check_example_measurements"](inventory, plans)


@pytest.mark.parametrize("field", ["by", "date", "instrument", "status"])
def test_actual_pedro_metadata_cannot_be_rewritten_as_demo_facts(worked_example_data, field):
    original, plans = worked_example_data
    inventory = copy.deepcopy(original)
    fact = inventory["fixtures"]["vise-pm-6"]["jaw_height_in"]
    physical = fact["value"]
    fact["measured"][field] = {
        "by": "example value (realistic, not a shop measurement)",
        "date": "2026-10-11",
        "instrument": "example fixture (no physical measurement)",
        "status": "assumed",
    }[field]
    assert fact["value"] == physical
    with pytest.raises(ValueError, match="actual Pedro measurement changed"):
        VALIDATOR["check_example_measurements"](inventory, plans)


def test_assumed_lead_debt_does_not_demote_the_selected_diameters(worked_example_data):
    inventory, _ = worked_example_data
    entries = VALIDATOR["Entries"](inventory)
    for member, diameter in (("0.4500in", 11.430), ("0.4835in", 12.281)):
        reference = f"reamers-decimal/{member}"
        fact = inventory["tools"]["reamers-decimal"]["members"][member]["lead_mm"]
        assert fact["value"] == 1.0
        assert fact["measured"]["status"] == "assumed"
        assert VALIDATOR["tool_length_mm"](reference, "lead", entries) == "unknown"
        assert VALIDATOR["tool_length_mm"](reference, "dia", entries) == diameter
        assert VALIDATOR["tool_length_mm"](reference, "flute_len", entries) == 44.5


def test_worked_example_authored_exit_targets_remain_exact():
    assert VALIDATOR["EXPECTED_EXIT"] == {
        "pivot-shaft": 0,
        "rocker-arm": 0,
        "pivot-bracket": 0,
        "cone-pivot-post/built-up.toml": 4,
    }
