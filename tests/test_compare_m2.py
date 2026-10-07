"""Authored scratch candidates: construction, volume provenance and compare safety."""

import json
import math

import pytest
from test_cli import run_cli

STOCK = """[stock]
form = "flat_bar"
section_mm = [2.0, 5.0]
length_mm = 10.0
cite = "scratch candidate blank dimensions"
"""
ROUND = """[stock]
form = "round_bar"
dia_mm = 2.0
length_mm = 10.0
cite = ["scratch round diameter", "scratch round length"]
"""
COMPONENTS = """[stock]
form = "built_up"
# Enclosing dimensions must not be counted as an extra blank.
section_mm = [100.0, 100.0]
length_mm = 100.0
cite = "scratch assembly candidate"
[[stock.components]]
id = "round"
form = "round_bar"
dia_mm = 2.0
length_mm = 10.0
cite = "scratch component round dimensions"
[[stock.components]]
id = "block"
form = "flat_bar"
section_mm = [2.0, 5.0]
length_mm = 10.0
cite = "scratch component rectangular dimensions"
"""
HOLD = """fixture = "primary"
fixed_jaw = "not_applicable"
stop = "none"
grip_mm = "not_applicable"
clamp = "not_applicable"
"""
INVENTORY = """[machines.mill]
kind = "mill"
verify = false
[machines.BS-0]
kind = "dividing_head"
verify = false
[fixtures.primary]
kind = "fixture_plate"
verify = false
"""


def candidate(
    root,
    name,
    *,
    construction="one_piece",
    permission="one_piece",
    stock=STOCK,
    net=50.0,
    net_cite="scratch exported CAD net volume",
    hold=HOLD,
    setups=1,
    inventory=INVENTORY,
):
    root.mkdir(parents=True, exist_ok=True)
    for filename, text in (
        ("inventory.toml", inventory),
        ("policy.toml", '[required]\nconstruction = "*"\n'),
        ("cutting.toml", "revision = 1\n"),
    ):
        (root / filename).write_text(text, encoding="utf-8")
    features = 'part = "scratch"\nunits = "mm"\nframes = "unknown"\n'
    if permission is not None:
        features += f"construction = {json.dumps(permission)}\n"
    if net is not None:
        features += f"volume_mm3 = {json.dumps(net)}\n"
    if net_cite is not None:
        features += f"volume_cite = {json.dumps(net_cite)}\n"
    features += """cite = {construction = "scratch drawing construction note"}
[features.subject]
kind = "face"
requirements = []
"""
    (root / f"{name}-features.toml").write_text(features, encoding="utf-8")
    plan = f'part = "scratch"\nfeatures = "{name}-features.toml"\n'
    if construction is not None:
        plan += f"construction = {json.dumps(construction)}\n"
    plan += (
        stock
        + """[paths]
inventory = "inventory.toml"
policy = "policy.toml"
cutting_data = "cutting.toml"
"""
    )
    for index in range(setups):
        plan += f"""[[setups]]
id = "S{index + 1}"
machine = "mill"
frame = "unknown"
coolant = "none"
deburr_mm = "unknown"
zero = "unknown"
[setups.stock_state]
top_z = 0.0
bottom_z = -1.0
[setups.hold]
{hold}
[[setups.ops]]
op = 10
do = "inspect"
feature = "subject"
tool = "unknown"
holder = "unknown"
checks = "unknown"
"""
    path = root / f"{name}.toml"
    path.write_text(plan, encoding="utf-8")
    return path


def compare(plans, out, expected_exit=0, *, json_output=True):
    args = ["compare", *plans, "--out", out]
    if json_output:
        args.append("--json")
    result = run_cli(*args)
    assert result.returncode == expected_exit, result.stderr
    rows = json.loads((out / "compare.json").read_bytes()) if expected_exit != 3 else None
    if json_output and rows is not None:
        assert json.loads(result.stdout) == rows
    return result, rows


def construction_finding(row):
    return next(finding for finding in row["rule_findings"] if finding["rule"] == "construction")


@pytest.mark.parametrize(
    ("construction", "permission", "status", "code"),
    [
        ("one_piece", "one_piece", "pass", 0),
        ("one_piece", "built_up_permitted", "pass", 0),
        ("built_up", "built_up_permitted", "pass", 0),
        ("built_up", "one_piece", "error", 2),
        ("built_up", "another_known_drawing_restriction", "error", 2),
        ("built_up", "unknown", "error", 2),
        ("built_up", None, "error", 2),
        ("built_up", " ", "error", 2),
        ("one_piece", "unknown", "pass", 0),
        ("one_piece", None, "pass", 0),
        ("unknown", "one_piece", "unknown", 4),
        ("unknown", "built_up_permitted", "unknown", 4),
        ("unknown", None, "unknown", 4),
        (None, "one_piece", "unknown", 4),
    ],
)
def test_construction_gate_uses_explicit_candidate_and_drawing_permission(
    tmp_path, request, construction, permission, status, code
):
    if code == 0:
        request.getfixturevalue("freecad_kernel")
    plan = candidate(
        tmp_path / "inputs", "candidate", construction=construction, permission=permission
    )
    _, rows = compare([plan], tmp_path / "out", code)
    finding = construction_finding(rows[0])
    assert finding["status"] == status
    assert finding["numbers"] == {
        "plan_construction": construction or "unknown",
        "drawing_construction": permission or "unknown",
    }
    if status == "error":
        assert finding["message"] == "drawing permits one-piece only"
    assert "scratch drawing construction note" in finding["cite"]


@pytest.mark.parametrize("verb", ["check", "traveler"])
@pytest.mark.parametrize("permission", ["one_piece", "unknown", None])
def test_construction_refusal_cannot_be_bypassed_outside_compare(tmp_path, verb, permission):
    plan = candidate(tmp_path / "inputs", "built", construction="built_up", permission=permission)
    out = tmp_path / "out"
    result = run_cli(verb, plan, "--out", out)
    assert result.returncode == 2, result.stderr
    findings = json.loads((out / "report.json").read_bytes())["findings"]
    assert next(f for f in findings if f["rule"] == "construction")["message"] == (
        "drawing permits one-piece only"
    )


@pytest.mark.parametrize(
    ("stock", "expected_stock", "net", "expected_waste"),
    [
        (STOCK, 100.0, 50.0, 0.5),
        (STOCK, 100.0, 100.0, 0.0),
        (STOCK, 100.0, 0.0, 1.0),
        (ROUND, 10.0 * math.pi, 5.0 * math.pi, 0.5),
        (COMPONENTS, 100.0 + 10.0 * math.pi, 50.0, 1.0 - 50.0 / (100.0 + 10.0 * math.pi)),
    ],
)
def test_sourced_waste_counts_authored_blank_or_leaf_components_once(
    tmp_path, freecad_kernel, stock, expected_stock, net, expected_waste
):
    plan = candidate(tmp_path / "inputs", "volume", stock=stock, net=net)
    _, rows = compare([plan], tmp_path / "out")
    row = rows[0]
    assert row["stock_volume_mm3"] == pytest.approx(expected_stock)
    assert row["net_volume_mm3"] == net
    assert row["waste_ratio"] == pytest.approx(expected_waste)
    assert row["volume_evidence"]["formula"] == (
        "(stock_volume_mm3 - net_volume_mm3) / stock_volume_mm3"
    )
    assert row["volume_evidence"]["net_cite"] == ["scratch exported CAD net volume"]
    assert "scratch exported CAD net volume" in row["cite"]
    pieces = row["volume_evidence"]["stock_components"]
    assert sum(piece["volume_mm3"] for piece in pieces) == pytest.approx(expected_stock)
    assert all(any("volume.toml:stock" in source for source in piece["cite"]) for piece in pieces)
    if stock == COMPONENTS:
        assert {source for piece in pieces for source in piece["cite"]} >= {
            "scratch component round dimensions",
            "scratch component rectangular dimensions",
        }


@pytest.mark.parametrize(
    "stock",
    [
        'stock = "unknown"\n',
        STOCK.replace('form = "flat_bar"', 'form = "unknown"'),
        STOCK.replace('form = "flat_bar"', 'form = "hollow_section"'),
        STOCK.replace("section_mm = [2.0, 5.0]", 'section_mm = [2.0, "unknown"]'),
        STOCK.replace("length_mm = 10.0\n", ""),
        STOCK.replace("length_mm = 10.0", 'length_mm = "unknown"'),
        ROUND.replace("dia_mm = 2.0", 'dia_mm = "unknown"'),
        COMPONENTS.replace("dia_mm = 2.0", 'dia_mm = "unknown"'),
        STOCK + 'components = "unknown"\n',
    ],
)
def test_unknown_blank_inputs_never_become_geometric_estimates(tmp_path, freecad_kernel, stock):
    plan = candidate(tmp_path / "inputs", "unknown-stock", stock=stock)
    _, rows = compare([plan], tmp_path / "out")
    assert rows[0]["stock_volume_mm3"] == "unknown"
    assert rows[0]["waste_ratio"] == "unknown"


@pytest.mark.parametrize(
    ("net", "net_cite"),
    [
        (None, "scratch exported CAD net volume"),
        ("unknown", "scratch exported CAD net volume"),
        (50.0, None),
        (50.0, "unknown"),
        (50.0, ""),
        (50.0, "   "),
        (50.0, []),
        (50.0, ["unknown", " "]),
    ],
)
def test_net_volume_needs_a_number_and_a_real_explicit_source(
    tmp_path, freecad_kernel, net, net_cite
):
    plan = candidate(tmp_path / "inputs", "unknown-net", net=net, net_cite=net_cite)
    result, rows = compare([plan], tmp_path / "out", json_output=False)
    assert rows[0]["net_volume_mm3"] == "unknown"
    assert rows[0]["waste_ratio"] == "unknown"
    assert " | ? | " in result.stdout


@pytest.mark.parametrize(
    ("stock", "net"),
    [
        (STOCK.replace("length_mm = 10.0", "length_mm = 0.0"), 50.0),
        (ROUND.replace("dia_mm = 2.0", "dia_mm = -2.0"), 50.0),
        (STOCK.replace("section_mm = [2.0, 5.0]", "section_mm = [2.0]"), 50.0),
        (STOCK.replace("section_mm = [2.0, 5.0]", "section_mm = []"), 50.0),
        (STOCK.replace("section_mm = [2.0, 5.0]", "section_mm = [2.0, -5.0]"), 50.0),
        (STOCK + "components = []\n", 50.0),
        (ROUND.replace("dia_mm = 2.0", "dia_mm = 1e308"), 50.0),
        (COMPONENTS.replace("dia_mm = 2.0", "dia_mm = 0.0"), 50.0),
        (STOCK, -1.0),
        (STOCK, 100.0001),
    ],
)
def test_invalid_volume_inputs_precede_rule_errors_and_preserve_prior_outputs(tmp_path, stock, net):
    plan = candidate(tmp_path / "inputs", "invalid", stock=stock, net=net, construction="built_up")
    out = tmp_path / "out"
    out.mkdir()
    output = out / "compare.json"
    output.write_bytes(b"earlier comparison\n")
    before = output.read_bytes()
    result, _ = compare([plan], out, 3)
    assert "Traceback" not in result.stderr
    assert output.read_bytes() == before
    assert {path.name for path in out.iterdir()} == {"compare.json"}


@pytest.mark.parametrize(
    "stock",
    [
        ROUND.replace('form = "round_bar"', 'form = "unknown"').replace(
            "dia_mm = 2.0", "dia_mm = -2.0"
        ),
        STOCK.replace('form = "flat_bar"', 'form = "unknown"').replace(
            "section_mm = [2.0, 5.0]", "section_mm = [2.0, -5.0]"
        ),
        ROUND + "section_mm = [2.0, -5.0]\n",
        ROUND + "section_mm = [2.0]\n",
        COMPONENTS.replace("section_mm = [100.0, 100.0]", "section_mm = [-100.0, 100.0]"),
        COMPONENTS.replace('form = "built_up"', 'form = "built_up"\ndia_mm = -1.0'),
    ],
)
def test_invalid_otherwise_unused_stock_dimensions_exit_three_without_output(tmp_path, stock):
    plan = candidate(tmp_path / "inputs", "invalid-unused", stock=stock, net=10.0)
    out = tmp_path / "out"
    result, _ = compare([plan], out, 3)
    assert "Traceback" not in result.stderr
    assert not out.exists()


def test_compare_lists_every_authored_workholding_identity_including_machine_index(
    tmp_path, freecad_kernel
):
    hold = """fixture = "primary"
fixed_jaw = "not_applicable"
stop = "stop"
grip_mm = "not_applicable"
clamp = "clamp"
parallels = "parallels"
support = "tailstock"
supports = ["steady", {ref = "riserA", orientation = "authored orientation"}, "tailstock"]
riser = "riserB"
locator = "locator"
jaw_protection = "soft_jaws"
index = {fixture = "BS-0", angle_deg = "unknown", positions = "unknown"}
"""
    expected = {
        "primary",
        "stop",
        "clamp",
        "parallels",
        "tailstock",
        "steady",
        "riserA",
        "riserB",
        "locator",
        "soft_jaws",
        "BS-0",
    }
    inventory = INVENTORY + "".join(
        f'\n[fixtures.{identity}]\nkind = "support"\nverify = false\n'
        for identity in sorted(expected - {"primary", "BS-0"})
    )
    plan = candidate(tmp_path / "inputs", "fixtures", hold=hold, inventory=inventory, setups=2)
    _, rows = compare([plan], tmp_path / "out")
    assert rows[0]["fixtures"] == sorted(expected)
    assert rows[0]["setups"] == 2


@pytest.mark.parametrize(
    ("hold", "code"),
    [
        (
            'fixture = "unknown"\nfixed_jaw = "not_applicable"\nstop = "none"\n'
            'grip_mm = "not_applicable"\nclamp = "not_applicable"\n',
            0,
        ),
        # An unresolved support may be a centre, so the always-required centre_support blocks.
        (HOLD + 'support = "unknown"\n', 4),
        (HOLD + 'supports = ["unknown", {ref = "unknown"}]\n', 4),
        (HOLD + "supports = [{}]\n", 4),
        (HOLD + 'index = "unknown"\n', 0),
    ],
)
def test_explicit_unknown_fixtures_remain_visible_without_none_sentinels(
    tmp_path, freecad_kernel, hold, code
):
    plan = candidate(tmp_path / "inputs", "unknown-fixture", hold=hold)
    _, rows = compare([plan], tmp_path / "out", code)
    assert "unknown" in rows[0]["fixtures"]
    assert "none" not in rows[0]["fixtures"]
    assert "not_applicable" not in rows[0]["fixtures"]


def test_same_part_candidate_paths_findings_and_messages_are_distinct_side_by_side(tmp_path):
    first = candidate(tmp_path / "left", "plan", setups=2)
    second = candidate(tmp_path / "right", "plan", construction="built_up")
    result, rows = compare([first, second], tmp_path / "out", 2, json_output=False)
    assert [row["plan"] for row in rows] == ["left/plan.toml", "right/plan.toml"]
    assert [row["part"] for row in rows] == ["scratch", "scratch"]
    assert [row["setups"] for row in rows] == [2, 1]
    assert [construction_finding(row)["status"] for row in rows] == ["pass", "error"]
    matrix_row = next(
        line for line in result.stdout.splitlines() if line.startswith("construction:")
    )
    assert " | ✗ drawing permits one-piece only" in matrix_row
    assert "left/plan.toml | right/plan.toml" in result.stdout


@pytest.mark.parametrize(
    ("states", "code"),
    [
        (("one_piece", "one_piece", "one_piece"), 0),
        (("one_piece", "unknown", "one_piece"), 4),
        (("unknown", "built_up", "one_piece"), 2),
        (("built_up", "unknown", "one_piece"), 2),
    ],
)
def test_many_candidate_exit_precedence_uses_shared_findings(
    tmp_path, freecad_kernel, states, code
):
    plans = [
        candidate(tmp_path / "inputs", f"candidate-{index}", construction=state)
        for index, state in enumerate(states)
    ]
    _, rows = compare(plans, tmp_path / "out", code)
    assert [row["exit"] for row in rows] == [
        {"one_piece": 0, "unknown": 4, "built_up": 2}[state] for state in states
    ]


def test_compare_json_repeats_byte_for_byte_and_keeps_numeric_citations(tmp_path, freecad_kernel):
    plans = [
        candidate(tmp_path / "inputs", "round", stock=ROUND, net=10.0),
        candidate(
            tmp_path / "inputs",
            "built",
            stock=COMPONENTS,
            construction="built_up",
            permission="built_up_permitted",
        ),
    ]
    out = tmp_path / "out"
    compare(plans, out)
    before = (out / "compare.json").read_bytes()
    compare(plans, out)
    assert (out / "compare.json").read_bytes() == before
    rows = json.loads(before)
    assert "scratch round diameter" in rows[0]["cite"]
    assert "scratch exported CAD net volume" in rows[1]["cite"]


@pytest.mark.parametrize("bad_first", [False, True])
def test_any_invalid_candidate_wins_before_errors_and_unknowns_without_output(tmp_path, bad_first):
    refused = candidate(tmp_path / "inputs", "refused", construction="built_up")
    unknown = candidate(tmp_path / "inputs", "unknown", construction=None)
    bad = candidate(tmp_path / "inputs", "bad")
    bad.write_text(
        bad.read_text(encoding="utf-8").replace('do = "inspect"', "do = true"), encoding="utf-8"
    )
    plans = [bad, refused, unknown] if bad_first else [refused, unknown, bad]
    out = tmp_path / "out"
    result, _ = compare(plans, out, 3)
    assert "Traceback" not in result.stderr
    assert not out.exists()


def test_compare_output_guard_includes_nonfirst_candidate_inputs(tmp_path):
    first = candidate(tmp_path / "left", "plan")
    out = tmp_path / "right"
    second = candidate(out, "plan")
    inventory = out / "compare.json"
    inventory.write_text(INVENTORY, encoding="utf-8")
    second.write_text(
        second.read_text(encoding="utf-8").replace(
            'inventory = "inventory.toml"', 'inventory = "compare.json"'
        ),
        encoding="utf-8",
    )
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    result, _ = compare([first, second], out, 3)
    assert "Traceback" not in result.stderr
    assert {path.name: path.read_bytes() for path in out.iterdir()} == before
