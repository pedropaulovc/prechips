"""A stopped-spindle die route selects real hand tooling, not a spindle stack."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_sheet_ops import Markup, content

from prechips.inputs import Bundle, load_bundle
from prechips.rules import tool_resolves
from prechips.rules.resolution import HAND_FINISH, HAND_THREAD, MANUAL, resolve, tool_numbers
from prechips.rules.zero_recipe.tool_setting import tool_changes, tool_setting
from prechips.sheet import render_traveler


@pytest.fixture
def die_bundle(tmp_path):
    return Bundle(
        features={
            "features": {
                "stud": {
                    "kind": "external_thread",
                    "thread": "1/4-20 UNC",
                    "thread_hand": "right",
                    "thread_class": "2A",
                }
            }
        },
        plan={
            "setups": [
                {
                    "id": "S1",
                    "machine": "lathe",
                    "ops": [
                        {
                            "op": 10,
                            "do": "die_thread",
                            "feature": "stud",
                            "tool": "dies/quarter",
                            "holder": "tools.stock",
                        }
                    ],
                }
            ]
        },
        inventory={
            "machines": {"lathe": {"kind": "lathe", "verify": False}},
            "tools": {
                "dies": {
                    "kind": "die_set",
                    "verify": False,
                    "members": {
                        "quarter": {
                            "thread": "1/4-20 UNC",
                            "thread_hand": "right",
                            "thread_class": "2A",
                        }
                    },
                },
                "stock": {
                    "kind": "die_stock",
                    "fits": "tools.dies/quarter",
                    "verify": False,
                },
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )


def assembly(bundle):
    return next(row for row in tool_resolves.evaluate(bundle) if row.subject == "S1:10")


def member(bundle):
    return bundle.inventory["tools"]["dies"]["members"]["quarter"]


def test_die_thread_is_manual_material_cut_not_hand_finish(die_bundle):
    assert HAND_THREAD == frozenset({"die_thread", "hand_tap"})
    assert "die_thread" in MANUAL
    assert "die_thread" not in HAND_FINISH
    assert resolve(die_bundle, "tools", "dies") is None
    assert resolve(die_bundle, "tools", "dies/quarter")["kind"] == "die_set"
    assert assembly(die_bundle).status == "pass"
    assert all(row.status == "pass" for row in tool_resolves.evaluate(die_bundle))
    setup = die_bundle.plan["setups"][0]
    assert tool_numbers(die_bundle, setup) == {
        (("tools", "dies/quarter"), ("tools", "stock")): "T1"
    }


@pytest.mark.parametrize(
    "field,value",
    [("kind", "tap"), ("thread", "1/4-28 UNF"), ("thread_hand", "left"), ("thread_class", "3A")],
)
def test_known_wrong_die_kind_spec_hand_or_class_is_error(die_bundle, field, value):
    member(die_bundle)[field] = value
    assert assembly(die_bundle).status == "error"


@pytest.mark.parametrize("field", ["thread", "thread_hand", "thread_class"])
@pytest.mark.parametrize("owner", ["die", "feature"])
@pytest.mark.parametrize("missing", [False, True])
def test_unknown_thread_identity_never_passes(die_bundle, field, owner, missing):
    item = member(die_bundle) if owner == "die" else die_bundle.features["features"]["stud"]
    if missing:
        item.pop(field)
    else:
        item[field] = "unknown"
    assert assembly(die_bundle).status == "unknown"


@pytest.mark.parametrize("field", ["tool", "holder"])
def test_missing_die_or_stock_is_unknown_including_selected_identity(die_bundle, field):
    die_bundle.plan["setups"][0]["ops"][0][field] = "missing"
    rows = tool_resolves.evaluate(die_bundle)
    assert assembly(die_bundle).status == "unknown"
    assert next(row for row in rows if row.subject == "missing").status == "unknown"


def test_undeclared_member_is_error_but_unselected_set_is_unknown(die_bundle):
    op = die_bundle.plan["setups"][0]["ops"][0]
    op["tool"] = "dies/not-a-member"
    assert assembly(die_bundle).status == "error"
    op["tool"] = "dies"
    die_bundle.inventory["tools"]["stock"]["fits"] = "dies"
    assert assembly(die_bundle).status == "unknown"


@pytest.mark.parametrize("kind", ["collet", "tap_wrench"])
def test_wrong_stock_kind_is_error(die_bundle, kind):
    die_bundle.inventory["tools"]["stock"]["kind"] = kind
    assert assembly(die_bundle).status == "error"


@pytest.mark.parametrize("fits,status", [("unknown", "unknown"), ("dies/other", "error")])
def test_stock_fit_requires_selected_member_identity(die_bundle, fits, status):
    die_bundle.inventory["tools"]["stock"]["fits"] = fits
    assert assembly(die_bundle).status == status


def test_uncertain_die_or_stock_never_passes(die_bundle):
    member(die_bundle)["verify"] = True
    assert assembly(die_bundle).status == "unknown"
    member(die_bundle)["verify"] = False
    die_bundle.inventory["tools"]["stock"]["verify"] = True
    assert assembly(die_bundle).status == "unknown"


def test_die_does_not_require_toolpost_setting_even_if_touch_is_authored(die_bundle):
    setup = die_bundle.plan["setups"][0]
    zero = {"x": {"tool": "dies/quarter"}, "z": {"tool": "dies/quarter"}}
    touches = [{"tool": "dies/quarter", "before_ops": [10]}]
    assert tool_setting(die_bundle, setup, zero, touches, []) == []


def test_manual_die_does_not_change_spindle_tool_or_require_retouch(die_bundle):
    setup = die_bundle.plan["setups"][0]
    assert tool_changes(die_bundle, setup, {}, True, "unknown", []) == (
        [],
        [],
        False,
        {},
        {},
    )
    die_bundle.inventory["tools"]["turner"] = {"kind": "turning_tool", "verify": False}
    setup["ops"].extend(
        [
            {"op": 20, "do": "turn", "tool": "turner", "feature": "stud"},
            {**setup["ops"][0], "op": 30},
            {"op": 40, "do": "turn", "tool": "tools.turner", "feature": "stud"},
        ]
    )
    zero = {"x": {"tool": "turner"}}
    derived, missing, unknown, readings, served = tool_changes(
        die_bundle,
        setup,
        zero,
        True,
        "unknown",
        [],
    )
    assert derived == missing == []
    assert unknown is False
    assert set(readings) == {"20", "40"}
    assert served == {}


def test_die_requires_an_external_thread_feature(die_bundle):
    die_bundle.features["features"]["stud"]["kind"] = "threaded_hole"
    assert assembly(die_bundle).status == "error"


def test_supported_designation_spelling_and_qualified_identity_match(die_bundle):
    member(die_bundle)["thread"] = "1/4-20 unc"
    member(die_bundle)["thread_class"] = "2a"
    die_bundle.plan["setups"][0]["ops"][0]["tool"] = "tools.dies/quarter"
    assert assembly(die_bundle).status == "pass"


def test_known_wrong_die_is_not_hidden_by_missing_holder(die_bundle):
    member(die_bundle)["thread_hand"] = "left"
    die_bundle.plan["setups"][0]["ops"][0].pop("holder")
    assert assembly(die_bundle).status == "error"


@pytest.mark.parametrize("rpm", [-100, 100])
def test_manual_die_rejects_a_powered_spindle_speed(die_bundle, rpm):
    die_bundle.plan["setups"][0]["ops"][0]["rpm"] = rpm
    row = assembly(die_bundle)
    assert row.status == "error"
    assert "stopped spindle" in row.sentence


@pytest.fixture
def tap_bundle(die_bundle):
    feature = die_bundle.features["features"]["stud"]
    feature.update(kind="threaded_hole", thread_class="2B")
    tools = die_bundle.inventory["tools"]
    tools["taps"] = {
        "kind": "tap_set",
        "verify": False,
        "members": {
            "quarter": {
                "thread": "1/4-20 UNC",
                "thread_hand": "right",
                "thread_class": "2B",
                "dia_mm": 6.35,
            }
        },
    }
    tools["wrench"] = {"kind": "tap_wrench", "range_mm": [3.0, 8.0], "verify": False}
    op = die_bundle.plan["setups"][0]["ops"][0]
    op.update(do="hand_tap", tool="taps/quarter", holder="tools.wrench")
    return die_bundle


@pytest.mark.parametrize(
    "example,expected",
    [
        (
            "blondihacks-magic-tube",
            [
                ("C1", "die_thread", "die", ("tailstock", "die holder"), "1/2-20"),
                ("T2", "hand_tap", "tap", ("tap wrench",), "1/2-20"),
            ],
        ),
        (
            "blondihacks-t-nuts",
            [("D1", "hand_tap", "tap", ("tap follower",), "3/8-16")],
        ),
    ],
)
def test_public_tool_pull_lists_hand_threads_with_their_actual_holders(example, expected):
    bundle = load_bundle(Path(__file__).resolve().parents[1] / "examples" / example / "plan.toml")
    markup = Markup(render_traveler(bundle, [], {}))
    for setup_id, action, tool_role, holder_roles, thread in expected:
        setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == setup_id)
        op = next(op for op in setup["ops"] if op["do"] == action)
        (page,) = [
            page
            for page in markup.find("page")
            if page["attrs"]["data-sheet"] == f"SETUP {setup_id} sheet 1"
        ]
        (table,) = markup.find("tools", page)
        rows = []
        for row in markup.nodes:
            if (
                row["tag"] == "tr"
                and row["parent"]["tag"] == "tbody"
                and row["parent"]["parent"] is table
            ):
                rows.append(
                    [
                        content(cell).strip()
                        for cell in markup.nodes
                        if cell["tag"] == "td" and cell["parent"] is row
                    ]
                )
        (pulled,) = [row for row in rows if str(op["op"]) in row[4].split(", ")]
        assert re.fullmatch(r"T[1-9]\d*", pulled[0])
        assert thread in pulled[1]
        assert re.search(rf"\b{tool_role}\b", pulled[1], re.IGNORECASE)
        for role in holder_roles:
            assert role in pulled[3].casefold()
        (operation,) = [
            node
            for node in markup.find("operation", page)
            if node["attrs"]["data-op"] == str(op["op"])
        ]
        (tool_field,) = markup.find("op-tool", operation)
        (tool_value,) = [
            node for node in markup.nodes if node["tag"] == "dd" and node["parent"] is tool_field
        ]
        assert " ".join(content(tool_value).split()) == pulled[0]
        # These source selections have no measured physical dimensions. A nominal
        # thread designation must not become a tool OD, projection or measurement debt.
        assert not re.search(r"\d|Ø|projection", pulled[2], re.IGNORECASE)


@pytest.mark.parametrize("fixture_name", ["die_bundle", "tap_bundle"])
def test_identity_only_context_leaves_thread_feature_unresolved(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    context = SimpleNamespace(plan=bundle.plan, inventory=bundle.inventory)
    rows = tool_resolves.evaluate(context)
    manual = next(row for row in rows if row.subject == "S1:10")
    assert manual.status == "unknown"
    for field in ("thread", "thread_hand", "thread_class"):
        assert manual.numbers[field]["required"] == "unknown"
    assert "thread feature identity is unknown" in manual.sentence
    identities = {row.numbers["reference"]: row for row in rows if "category" in row.numbers}
    tool = bundle.plan["setups"][0]["ops"][0]["tool"]
    assert tool in identities
    assert identities[tool].status == "pass"


def test_hand_tap_resolves_real_tap_and_nominal_wrench_capacity_without_spindle(tap_bundle):
    assert assembly(tap_bundle).status == "pass"
    assert all(row.status == "pass" for row in tool_resolves.evaluate(tap_bundle))
    setup = tap_bundle.plan["setups"][0]
    assert tool_changes(tap_bundle, setup, {}, True, "unknown", []) == (
        [],
        [],
        False,
        {},
        {},
    )
    zero = {"x": {"tool": "taps/quarter"}, "z": {"tool": "taps/quarter"}}
    assert tool_setting(tap_bundle, setup, zero, [], []) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "die"),
        ("thread", "1/4-28 UNF"),
        ("thread_hand", "left"),
        ("thread_class", "2A"),
    ],
)
def test_hand_tap_wrong_kind_spec_hand_or_class_is_error(tap_bundle, field, value):
    tap_bundle.inventory["tools"]["taps"]["members"]["quarter"][field] = value
    assert assembly(tap_bundle).status == "error"


@pytest.mark.parametrize("field", ["thread", "thread_hand", "thread_class", "dia_mm"])
def test_hand_tap_unknown_thread_or_capacity_inputs_do_not_pass(tap_bundle, field):
    tap_bundle.inventory["tools"]["taps"]["members"]["quarter"][field] = "unknown"
    assert assembly(tap_bundle).status == "unknown"


@pytest.mark.parametrize("holder", ["missing", "unknown"])
def test_hand_tap_missing_wrench_or_follower_is_unknown(tap_bundle, holder):
    tap_bundle.plan["setups"][0]["ops"][0]["holder"] = holder
    assert assembly(tap_bundle).status == "unknown"


def test_hand_tap_stock_and_chuck_are_not_hand_tap_holders(tap_bundle):
    tap_bundle.inventory["tools"]["wrench"]["kind"] = "die_stock"
    assert assembly(tap_bundle).status == "error"
    tap_bundle.inventory["tools"]["wrench"]["kind"] = "drill_chuck"
    assert assembly(tap_bundle).status == "error"


@pytest.mark.parametrize(
    "capacity,status",
    [
        ([3.0, 6.0], "error"),
        ([7.0, 8.0], "error"),
        ([3.0, 8.0], "pass"),
        ("unknown", "unknown"),
    ],
)
def test_hand_tap_nominal_capacity_boundaries(tap_bundle, capacity, status):
    tap_bundle.inventory["tools"]["wrench"]["range_mm"] = capacity
    assert assembly(tap_bundle).status == status


def test_hand_tap_follower_exact_identity_and_inch_capacity(tap_bundle):
    holder = tap_bundle.inventory["tools"]["wrench"]
    holder.update(kind="tap_follower", fits="tools.taps/quarter")
    holder.pop("range_mm")
    assert assembly(tap_bundle).status == "pass"
    holder["fits"] = "taps/wrong-member"
    assert assembly(tap_bundle).status == "error"
    holder.pop("fits")
    holder["range_in"] = [0.125, 0.375]
    assert assembly(tap_bundle).status == "pass"


def test_hand_tap_unselected_set_and_undeclared_member_do_not_pass(tap_bundle):
    op = tap_bundle.plan["setups"][0]["ops"][0]
    op["tool"] = "taps"
    assert assembly(tap_bundle).status == "unknown"
    op["tool"] = "taps/absent"
    assert assembly(tap_bundle).status == "error"


def test_hand_tap_wrong_feature_role_or_powered_rpm_is_error(tap_bundle):
    op = tap_bundle.plan["setups"][0]["ops"][0]
    op["rpm"] = 250
    assert assembly(tap_bundle).status == "error"
    op["rpm"] = 0
    assert assembly(tap_bundle).status == "pass"
    tap_bundle.features["features"]["stud"]["kind"] = "external_thread"
    assert assembly(tap_bundle).status == "error"
