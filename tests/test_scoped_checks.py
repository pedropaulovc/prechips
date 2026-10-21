"""Feature-scoped checks in a multi-feature inspect op (#250).

One inspection station reads several features, the same requirement name with a different
gauge on each: ``checks = { pivot_bore = { dia = ... }, hub_od = { dia = ... } }``. Flat
entries keep applying to every listed feature that exports them.
"""

import json
import re
from dataclasses import replace

import pytest
from test_cli import copy_examples
from test_consistency import bundle as consistency_bundle
from test_consistency import errors as consistency_errors
from test_process_route import append_op, checkpoint_result, evaluate, op_markup
from test_sheet_ops import content, ledger

from prechips.inputs import BadInput, load_bundle
from prechips.rules import tool_resolves

STATION = ["pivot_bore", "hub_od", "hub_faces"]
# The issue's station: the bore on pins, the hub OD and the hub faces on a micrometer.
ISSUE_CHECKS = (
    'checks = { pivot_bore = { dia = "pin-gauges" }, '
    'hub_od = { dia = "micrometers/0-1in" }, length = "micrometers/0-1in" }'
)


def station(tmp_path, *lines, features=STATION):
    """The rocker plan with one final inspect op reading ``features``; returns
    ``(plan, subject)``."""
    plan = copy_examples(tmp_path) / "rocker-arm" / "plan.toml"
    body = "\n".join(['do = "inspect"', f"feature = {json.dumps(features)}", *lines]) + "\n"
    return plan, append_op(plan, body)


# ------------------------------------------------------------------ the inspection rule


def test_each_listed_feature_is_judged_with_its_own_scoped_gauge(tmp_path):
    plan, subject = station(tmp_path, ISSUE_CHECKS)
    rows = evaluate("inspection", load_bundle(plan))
    for feature, requirement, gauge in (
        ("pivot_bore", "dia", "pin-gauges"),
        ("hub_od", "dia", "micrometers/0-1in"),
        ("hub_faces", "length", "micrometers/0-1in"),
    ):
        row = rows[f"{feature}:{requirement}"]
        assert (row.numbers["op"], row.numbers["gauge"]) == (subject, gauge)
        assert row.status == "pass", row.sentence


def test_a_flat_entry_still_applies_to_every_listed_feature(tmp_path):
    # Flat, the micrometer is the bore's gauge too, and it cannot read a hole's diameter:
    # the bore's own scoped gauge is what makes the station pass.
    plan, subject = station(tmp_path, 'checks = { dia = "micrometers/0-1in" }')
    rows = evaluate("inspection", load_bundle(plan))
    assert rows["hub_od:dia"].numbers["op"] == subject
    assert rows["hub_od:dia"].status == "pass"
    bore = rows["pivot_bore:dia"]
    assert (bore.numbers["gauge"], bore.status) == ("micrometers/0-1in", "error")
    assert "named gauge cannot measure this requirement" in bore.sentence


def test_a_scoped_go_no_go_pair_gauges_only_its_own_feature(tmp_path):
    plan, _ = station(
        tmp_path,
        'checks = { pivot_bore = { dia = "rocker-bore-limit-gauges" }, '
        'hub_od = { dia = "micrometers/0-1in" } }',
        "go_no_go = { pivot_bore = { dia = { go = 6.5, no_go = 6.53 } } }",
        features=["pivot_bore", "hub_od"],
    )
    data = load_bundle(plan)
    data.inventory["gauges"]["rocker-bore-limit-gauges"]["sizes_mm"] = [6.5, 6.53]
    rows = evaluate("inspection", data)
    bore = rows["pivot_bore:dia"]
    assert (bore.numbers["go_mm"], bore.numbers["no_go_mm"], bore.status) == (6.5, 6.53, "pass")
    assert "go_mm" not in rows["hub_od:dia"].numbers
    assert rows["hub_od:dia"].status == "pass"


def test_a_scoped_go_no_go_pair_outside_its_band_is_that_features_error(tmp_path):
    plan, _ = station(
        tmp_path,
        'checks = { pivot_bore = { dia = "rocker-bore-limit-gauges" }, '
        'hub_od = { dia = "micrometers/0-1in" } }',
        "go_no_go = { pivot_bore = { dia = { go = 6.49, no_go = 6.53 } } }",
        features=["pivot_bore", "hub_od"],
    )
    data = load_bundle(plan)
    data.inventory["gauges"]["rocker-bore-limit-gauges"]["sizes_mm"] = [6.49, 6.5, 6.53]
    rows = evaluate("inspection", data)
    assert rows["pivot_bore:dia"].status == "error"
    assert "GO / NO-GO sizes accept work outside the band" in rows["pivot_bore:dia"].sentence
    assert rows["hub_od:dia"].status == "pass"


def test_a_station_beside_a_prepared_blank_reads_no_end_face_from_its_feature_list(tmp_path):
    # The rocker squares a prepared blank: its end-face search once hashed the op's list.
    plan, _ = station(tmp_path, 'checks = { length = "micrometers/0-1in" }')
    # A synthetic kernel with no handed-on stock: the rule reads its route, cuts nothing.
    data = replace(load_bundle(plan), kernel={"status": "ok", "setups": {}})
    (row,) = evaluate("prepared_blank", data).values()
    assert row.numbers["made_by"]  # the end faces the prep setups cut, found past the list
    assert row.status == "unknown" and "reports no stock" in row.sentence


def test_a_scoped_gauge_missing_from_the_inventory_is_still_a_named_item(tmp_path):
    plan, subject = station(
        tmp_path,
        'checks = { pivot_bore = { dia = "pin-gauges" }, hub_od = { dia = "no-such-gauge" } }',
        features=["pivot_bore", "hub_od"],
    )
    findings = tool_resolves.evaluate(load_bundle(plan))
    named = [f for f in findings if f.status == "error" and "no-such-gauge" in f.sentence]
    assert named, [f.sentence for f in findings if f.status == "error"]


def test_scoped_method_text_meets_the_no_go_plug_contradiction_check():
    op = {
        "op": 34,
        "do": "inspect",
        "feature": ["rod_hole", "pivot_bore"],
        "checks": {"rod_hole": {"dia": "plugs"}, "pivot_bore": {"dia": "pins"}},
        "go_no_go": {"rod_hole": {"dia": {"go": 2.0, "no_go": 2.09}}},
        "inspection_methods": {
            "rod_hole": {"dia": "Push the NO-GO plug (2.090) through the strap."},
            "pivot_bore": {"dia": "Push each pin through the bore."},
        },
    }
    found = consistency_errors(consistency_bundle([{"ops": [op]}]))["S1:34"]
    assert "the dia inspection text passes the NO-GO plug through" in found
    assert "NO-GO 2.09" in found
    assert "Push each pin through the bore" not in found


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    ("lines", "match"),
    [
        # A scope key the op does not list.
        (
            ['checks = { pivot_bore = { dia = "pin-gauges" }, rod_hole = { dia = "pin-gauges" } }'],
            r"checks\.rod_hole scopes entries to a feature the op does not list",
        ),
        # A scoped requirement its feature does not export.
        (
            ['checks = { hub_od = { length = "micrometers/0-1in" } }'],
            r"checks\.hub_od\.length is not one of hub_od's exported requirements; use "
            "missing_requirements",
        ),
        # One requirement both flat and scoped in one table.
        (
            ['checks = { dia = "pin-gauges", hub_od = { dia = "micrometers/0-1in" } }'],
            r"checks\.dia is given both for every listed feature and for hub_od alone",
        ),
        (
            [
                ISSUE_CHECKS,
                'inspection_methods = { dia = "Read it.", hub_od = { dia = "Mike it." } }',
            ],
            r"inspection_methods\.dia is given both for every listed feature and for hub_od",
        ),
        # A scoped pair or method with no gauge for that feature's requirement.
        (
            [
                'checks = { length = "micrometers/0-1in" }',
                "go_no_go = { pivot_bore = { dia = { go = 6.5, no_go = 6.53 } } }",
            ],
            r"go_no_go\.pivot_bore\.dia names no checks gauge for pivot_bore",
        ),
        (
            [
                'checks = { pivot_bore = { dia = "pin-gauges" } }',
                'inspection_methods = { hub_od = { dia = "Mike it." } }',
            ],
            r"inspection_methods\.hub_od\.dia names no checks gauge for hub_od",
        ),
        # A flat pair applies to every listed feature that exports it: each needs a gauge.
        (
            [
                'checks = { pivot_bore = { dia = "pin-gauges" } }',
                "go_no_go = { dia = { go = 6.5, no_go = 6.53 } }",
            ],
            r"go_no_go\.dia names no checks gauge",
        ),
        # A GO / NO-GO pair keyed by a feature name, not a requirement.
        (
            [ISSUE_CHECKS, "go_no_go = { pivot_bore = { go = 6.5, no_go = 6.53 } }"],
            r"go_no_go\.pivot_bore names a listed feature: scope its entries as "
            r"go_no_go\.pivot_bore\.<requirement>",
        ),
        (
            ['checks = { pivot_bore = "pin-gauges" }'],
            r"checks\.pivot_bore names a listed feature",
        ),
    ],
)
def test_scoped_tables_reject_what_no_feature_can_read(tmp_path, lines, match):
    plan, _ = station(tmp_path, *lines)
    with pytest.raises(BadInput, match=match):
        load_bundle(plan)


@pytest.mark.parametrize(
    "pair",
    [
        '{ go = "unknown", no_go = "unknown" }',  # unknown sizes are not a table of entries
        '{ go = "unknown" }',  # a pair missing its NO-GO size
    ],
)
def test_a_malformed_flat_pair_never_passes_as_a_scoped_table(tmp_path, pair):
    plan, _ = station(tmp_path, ISSUE_CHECKS, f"go_no_go = {{ length = {pair} }}")
    with pytest.raises(BadInput, match="GO / NO-GO pair needs two positive sizes"):
        load_bundle(plan)


def test_a_process_hold_pair_on_another_feature_keeps_its_own_method_check():
    op = {
        "op": 34,
        "do": "inspect",
        "feature": ["rod_hole", "pivot_bore"],
        "checks": {"rod_hole": {"dia": "plugs"}, "pivot_bore": {"dia": "pins"}},
        "go_no_go": {"pivot_bore": {"dia": {"go": 6.5, "no_go": 6.53}}},
        "inspection_methods": {
            "rod_hole": {"dia": "Push the NO-GO plug through the strap."},
            "pivot_bore": {"dia": "The GO pin enters; the NO-GO pin does not."},
        },
        "process_holds": [
            {
                "feature": "rod_hole",
                "requirement": "dia",
                "band": [2.0, 2.01],
                "gauge": "plugs",
                "reason": "Pin fit for the next setup.",
                "go_no_go": {"go": 2.0, "no_go": 2.01},
            }
        ],
    }
    found = consistency_errors(consistency_bundle([{"ops": [op]}]))["S1:34"]
    assert "passes the NO-GO plug through" in found and "NO-GO 2.01" in found


def test_a_single_feature_op_keys_its_checks_by_requirement_alone(tmp_path):
    plan, _ = station(
        tmp_path, 'checks = { pivot_bore = { dia = "pin-gauges" } }', features="pivot_bore"
    )
    with pytest.raises(BadInput, match=r"checks\.pivot_bore scopes entries to the op's only"):
        load_bundle(plan)


def test_a_key_naming_both_a_listed_feature_and_an_exported_requirement_is_ambiguous(tmp_path):
    plan, _ = station(tmp_path, 'checks = { length = { length = "micrometers/0-1in" } }')
    manifest = plan.parent / "features.toml"
    text = manifest.read_text(encoding="utf-8")
    # A feature whose name is a requirement the station's hub faces export.
    manifest.write_text(
        text + '\n["features"."length"]\n"kind" = "face"\n"frame" = "model"\n'
        '"requirements" = ["length"]\n"length" = [1.0, 2.0]\n',
        encoding="utf-8",
    )
    lines = plan.read_text(encoding="utf-8").splitlines(keepends=True)
    lines = [
        line.replace('"hub_faces"]', '"hub_faces", "length"]')
        if line.startswith("feature = [")
        else line
        for line in lines
    ]
    plan.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(BadInput, match=r"checks\.length is both a listed feature and an export"):
        load_bundle(plan)


def test_inspection_views_illustrate_a_flat_method_only(tmp_path):
    view = (
        'inspection_views = { dia = [{ title = "Bore", up = [0.0, 0.0, 1.0], '
        'toward = [0.0, -1.0, 0.0], marks = [{ label = "A", at_mm = [0.0, 8.0, 0.0] }] }] }'
    )
    plan, _ = station(
        tmp_path,
        ISSUE_CHECKS,
        'inspection_methods = { pivot_bore = { dia = "Pins." }, hub_od = { dia = "Mike." } }',
        view,
    )
    with pytest.raises(BadInput, match="views are keyed by requirement alone"):
        load_bundle(plan)


# ------------------------------------------------------------------ the traveler


def test_the_station_card_prints_each_features_own_gauge():
    markup, _, _ = ledger(
        {
            "pivot_bore": {"kind": "hole", "requirements": ["dia"], "dia": [6.5, 6.53]},
            "hub_od": {"kind": "boss", "requirements": ["dia"], "dia": [9.69, 10.71]},
            "hub_faces": {"kind": "face", "requirements": ["length"], "length": [7.0565, 7.1065]},
        },
        [
            {
                "op": 100,
                "do": "inspect",
                "feature": STATION,
                "checks": {
                    "pivot_bore": {"dia": "pins"},
                    "hub_od": {"dia": "mic"},
                    "length": "mic",
                },
                "go_no_go": {"pivot_bore": {"dia": {"go": 6.5, "no_go": 6.53}}},
                "inspection_methods": {
                    "pivot_bore": {"dia": "Offer each plug by hand."},
                    "hub_od": {"dia": "Mike the hub at two places."},
                },
            }
        ],
    )
    (card,) = markup.find("operation")
    records = {
        tuple(json.loads(node["attrs"]["data-features"])): content(node)
        for node in markup.find("inspection-record", card)
    }
    assert set(records) == {("pivot_bore",), ("hub_od",), ("hub_faces",)}
    bore, hub, faces = records[("pivot_bore",)], records[("hub_od",)], records[("hub_faces",)]

    def band(text):
        (limits,) = re.findall(r"(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)", text)
        return tuple(map(float, limits))

    assert "Gauge pins" in bore and band(bore) == (6.5, 6.53) and "Gauge mic" not in bore
    pair = re.search(r"GO (\d+(?:\.\d+)?) enters, NO-GO (\d+(?:\.\d+)?) does not", bore)
    assert pair and tuple(map(float, pair.groups())) == (6.5, 6.53)
    assert "Gauge mic" in hub and band(hub) == (9.69, 10.71) and "GO" not in hub
    assert "Gauge mic" in faces and band(faces) == (7.057, 7.106)
    # Methods remain inline at the feature/gauge owner, not detached page-note pointers.
    bore_record = next(
        node
        for node in markup.find("inspection-record", card)
        if json.loads(node["attrs"]["data-features"]) == ["pivot_bore"]
    )
    hub_record = next(
        node
        for node in markup.find("inspection-record", card)
        if json.loads(node["attrs"]["data-features"]) == ["hub_od"]
    )
    faces_record = next(
        node
        for node in markup.find("inspection-record", card)
        if json.loads(node["attrs"]["data-features"]) == ["hub_faces"]
    )
    assert "Offer each plug by hand." in content(bore_record)
    assert "Mike the hub at two places." not in content(bore_record)
    assert "Mike the hub at two places." in content(hub_record)
    assert "Offer each plug by hand." not in content(hub_record)
    assert not markup.find("inspection-method", faces_record)
    assert content(card).count("Offer each plug by hand.") == 1
    assert content(card).count("Mike the hub at two places.") == 1
    for record in (bore_record, hub_record, faces_record):
        assert record["attrs"]["data-setup-id"] == "S1"
        assert record["attrs"]["data-op-id"] == "100"
        assert len(markup.find("result-field", record)) == 1


def test_a_flat_method_shared_by_two_gauges_prints_once():
    markup, _, _ = ledger(
        {
            "left": {"kind": "hole", "requirements": ["dia"], "dia": [6.5, 6.53]},
            "right": {"kind": "boss", "requirements": ["dia"], "dia": [9.7, 10.7]},
        },
        [
            {
                "op": 50,
                "do": "inspect",
                "feature": ["left", "right"],
                "checks": {"left": {"dia": "pins"}, "right": {"dia": "mic"}},
                "inspection_methods": {"dia": "Clean, then read. Record {reading}."},
            }
        ],
    )
    records = markup.find("inspection-record")
    assert [json.loads(node["attrs"]["data-features"]) for node in records] == [["left"], ["right"]]
    for record, gauge, limits in zip(
        records, ("Gauge pins", "Gauge mic"), ((6.5, 6.53), (9.7, 10.7)), strict=True
    ):
        shown = content(record)
        (band,) = re.findall(r"(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)", shown)
        assert tuple(map(float, band)) == limits
        assert gauge in shown
    (method,) = markup.find("inspection-method")
    assert content(method).count("Clean, then read.") == 1
    assert "Record" in content(method)
    assert len(markup.find("field", method)) == 1
    for record in records:
        assert record["attrs"]["data-setup-id"] == "S1"
        assert record["attrs"]["data-op-id"] == "50"
        assert len(markup.find("result-field", record)) == 1


def test_the_traveler_prints_one_station_card_for_the_issue_table(tmp_path):
    plan, subject = station(tmp_path, ISSUE_CHECKS)
    sid, op = subject.split(":")
    # The traveler's own op assembly, in process, on a synthetic kernel: no native job.
    markup, node = op_markup(plan, sid, op)
    (instruction,) = markup.find("route-operation", node)
    assert json.loads(instruction["attrs"]["data-features"]) == STATION
    assert all(name.replace("_", " ") in content(instruction) for name in STATION)
    criteria = markup.find("route-inspection", node)
    assert len(criteria) == 3
    bore, hub, faces = map(content, criteria)
    assert "pin" in bore.lower() and "0-1 in mic" not in bore
    assert "0-1 in mic" in hub and "pin" not in hub.lower()
    assert "0-1 in mic" in faces
    for feature, requirement in (
        ("pivot_bore", "dia"),
        ("hub_od", "dia"),
        ("hub_faces", "length"),
    ):
        checkpoint_result(markup, node, sid, op, [feature], requirement)
    assert len(markup.find("checkpoint-result", node)) == 3
