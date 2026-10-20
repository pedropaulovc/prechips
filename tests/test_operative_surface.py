"""One surface, one printed Z.

S1 finishes a face at an off-grid ``to_z``; the DRO cuts it at the checked ``dro_to_z``,
rounded up on S1's grid. S2 receives S1's stock, starts on that face, zeroes Z on it
and drills from it: every Z it prints for the face is that as-cut value, and every Z it
dials is on its own grid.
"""

import json
import re
from pathlib import Path

import pytest
from test_cli import SYNTHETIC_KERNEL, traveler
from test_envelope_m5 import measured
from test_headroom import coordinate_bundle
from test_sheet_ops import Markup, content, operation_instruction
from test_tool_change_touch import bundle as tool_change_bundle
from test_tool_change_touch import dro_paragraphs, mill_zero, op, zero_rows

from prechips.findings import Finding
from prechips.inputs import Bundle
from prechips.model import Features, Inventory, Plan
from prechips.rules import coordinates, tip_endpoints
from prechips.rules.zero_recipe import rule as zero_recipe_rule
from prechips.sheet import _Traveler

NOMINAL = -2.27825
STEP = 0.005
BLIND = 3.0
FEATURES = (
    "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-4.0, 0.0] }\n"
    "[features.hole]\nframe = 'model'\nkind = 'hole'\nrequirements = []\n"
    "at = [10.0, 5.0, -2.27825]\ndia = 6.0\nthru = true\n"
)
ZERO = "[setups.zero.z]\nface = '{}'\n{}method = 'paper'\npaper_mm = 0.05\ncheck_jog_mm = 10.0\n"
MILL = "[machines.mill]\nkind = 'mill'\n"


def setup(sid, touch_edge=NOMINAL):
    """A fine-grid setup receiving S1's stock; its touch names the standing face."""
    return (
        f"[[setups]]\nid = '{sid}'\nmachine = 'mill'\nframe = 'A'\nstock_in = 'S1'\n"
        "coolant = 'unknown'\ndeburr_mm = 'unknown'\n"
        "[setups.hold]\nfixture = 'unknown'\nstop = 'unknown'\ngrip_mm = 'unknown'\n"
        "clamp = 'unknown'\nfixed_jaw = 'unknown'\n"
        f"[setups.stock_state]\ntop_z = {NOMINAL}\nbottom_z = -10.0\n"
        f"entry_z = {{ hole = {NOMINAL} }}\nlocal_thickness = {{ hole = 7.72175 }}\n"
        + ZERO.format("target", f"edge_mm = {touch_edge}\n")
    )


def face(op, to_z):
    return (
        f"[[setups.ops]]\nop = {op}\ndo = 'finish_face'\nfeature = 'target'\ntool = 'cutter'\n"
        f"to_z = {to_z}\ndirection = 'conventional'\n"
    )


def bundle(tmp_path, features, operations, coarse=False):
    """The scratch bundle on an absolute up-reading DRO; mills on the 0.005 grid, S1's on
    0.010 when ``coarse``."""
    path = coordinate_bundle(tmp_path, features, operations, resolution=STEP)
    text = path.read_text(encoding="utf-8").replace(
        "[[setups]]",
        "[dro]\nmode = 'abs'\n[dro.direction]\nx = 'right'\ny = 'away'\nz = 'up'\n[[setups]]",
        1,
    )
    path.write_text(text.replace("machine = 'mill'", "machine = 'coarse'", int(coarse)), "utf-8")
    inventory = path.with_name("inventory.toml")
    stock = inventory.read_text(encoding="utf-8")
    coarse_mill = (
        stock[stock.index(MILL) :]
        .split("[tools.", 1)[0]
        .replace("machines.mill", "machines.coarse")
    )
    stock += coarse_mill.replace(
        f"resolution_mm = {{ value = {STEP},",
        f"resolution_mm = {{ value = {2 * STEP},",
        1,
    )
    inventory.write_text(stock, encoding="utf-8")
    return path


def plan(
    tmp_path,
    exit_mm=1.0,
    depth=None,
    do="drill",
    drilled=BLIND,
    coarse=False,
    detour=None,
    touch_edge=None,
):
    """S1 finishes ``target`` to Z -2.27825; S2, same frame, receives S1's stock, starts on
    it, zeroes Z on it and ``do``-s ``hole`` from it: through the 7.72175 mm below it,
    ``exit_mm`` past the exit face, or, given a ``depth`` band (or bare upper limit),
    blind and ``drilled`` deep. Given a ``detour`` Z, an S2 that also receives S1's stock
    refaces ``target`` to it first, and the consumer is S3, which never receives that cut.
    Coarse-source pickups touch its known as-cut -2.27, not the off-grid CAD nominal;
    CAD-native entry and local thickness remain unchanged."""
    features = FEATURES
    if depth is not None:
        features = FEATURES.replace("thru = true\n", f"thru = false\ndepth = {depth}\n")
    if touch_edge is None:
        touch_edge = -2.27 if coarse else NOMINAL
    operations = (
        ZERO.format("top", "")
        + face(10, NOMINAL)
        + (setup("S2", touch_edge) + face(10, detour) if detour is not None else "")
        + setup("S2" if detour is None else "S3", touch_edge)
        + f"[[setups.ops]]\nop = 10\ndo = '{do}'\nfeature = 'hole'\ntool = 'drill'\n"
        + (f"exit_mm = {exit_mm}\n" if depth is None else f"depth_mm = {drilled}\n")
    )
    return bundle(tmp_path, features, operations, coarse)


def on_grid(value):
    return value / STEP == pytest.approx(round(value / STEP), abs=1e-6)


class Readings(Markup):
    """Keep real line breaks in multi-line endpoint fields, not inline spans."""

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.handle_data("\n")
        super().handle_starttag(tag, attrs)


def printed(html):
    markup = Readings(html)
    lines = []
    for node in markup.nodes:
        if node["tag"] in {"p", "h2", "h3"}:
            lines.append(content(node))
        elif node["tag"] == "tr":
            cells = [
                content(cell)
                for cell in markup.nodes
                if cell["tag"] in {"td", "th"} and cell["parent"] is node
            ]
            lines.append("|" + "|".join(cells) + "|")
    return "\n".join(lines)


def zero(text, name):
    """The Z zero row on ``name``: surface, paper, Axis Set, jog, must read, if reversed."""
    match = re.search(
        rf"\|{name}; [^|]*surface at ([^;|]+); paper ([\d.]+)[^|]*\|([^|]+)\|\+Z ([^|]+)\|([^|]+)\|"
        r"([^|]+)\|",
        text,
    )
    return tuple(map(float, match.groups()))


def compact_datum(html, setup_id, name):
    """Read the operative surface and setting at their physical setup owner."""
    markup = Readings(html)
    values = {"surface": set(), "setting": set()}
    patterns = {
        "surface": rf"\b{re.escape(name)}; Z(-?\d+(?:\.\d+)?)(?![\d.])",
        "setting": r"\bAxis Set Z\s*(-?\d+(?:\.\d+)?)(?![\d.])",
    }
    for node in markup.nodes:
        if node["tag"] not in {"p", "span", "tr"}:
            continue
        owner = node
        while owner is not None:
            attrs = owner["attrs"]
            members = json.loads(attrs.get("data-setup-members", "[]"))
            if attrs.get("data-setup-id") or members:
                if attrs.get("data-setup-id") == setup_id or setup_id in members:
                    for field, pattern in patterns.items():
                        values[field].update(map(float, re.findall(pattern, content(node))))
                break
            owner = owner["parent"]
    (surface,) = values["surface"]
    (setting,) = values["setting"]
    return surface, setting


def evaluated_zero(report, setup_id):
    """Retain all checked zero arithmetic even when compact output omits its table."""
    (finding,) = [
        row
        for row in report["findings"]
        if (row["rule"], row["subject"]) == ("zero_check", setup_id)
    ]
    row = finding["numbers"]["axes"]["z"]
    assert row["axis_set_status"] == "computed"
    assert row["sign"] == 1
    setting, jog = row["axis_set"], row["jog_mm"]
    assert setting == pytest.approx(row["edge_mm"] + row["paper_mm"])
    assert (row["check_reading"], row["mirrored_reading"]) == pytest.approx(
        (setting + jog, setting - jog)
    )
    return row


def first_zero_example(html, setup_id, row, surface):
    markup = Readings(html)
    (guide,) = [
        node
        for node in markup.nodes
        if node["attrs"].get("id") == "dro-first-use"
        and node["attrs"].get("data-setup-id") == setup_id
    ]
    match = re.search(
        r"From Z (-?\d+(?:\.\d+)?), jog \+Z (\d+(?:\.\d+)?) mm: "
        r"expect (-?\d+(?:\.\d+)?); (-?\d+(?:\.\d+)?) = reversed",
        content(guide),
    )
    assert match is not None
    setting, jog = surface + row["paper_mm"], row["jog_mm"]
    assert tuple(map(float, match.groups())) == pytest.approx(
        (setting, jog, setting + jog, setting - jog)
    )


def endpoint_cell(html, entry, setup_id="S2"):
    """Read the physical operation's endpoint, independent of ledger/route layout."""
    markup = Readings(html)
    owner = operation_instruction(markup, setup_id, 10)
    targets = markup.find("op-target", within=owner)
    if targets:
        (target,) = targets
        (cell,) = [
            node for node in markup.nodes if node["tag"] == "dd" and node["parent"] is target
        ]
        text = content(cell)
    else:
        (instruction,) = markup.find("route-operation", within=owner)
        # The compact operation owner also carries its causal STOP decisions.
        text = content(owner)
    (shown_entry,) = re.findall(r"\bZ (-?\d+(?:\.\d+)?) → ", text)
    assert float(shown_entry) == entry
    return text


@pytest.mark.parametrize("coarse,checked", [(False, -2.275), (True, -2.27)])
def test_later_setup_prints_the_checked_as_cut_face(tmp_path, coarse, checked):
    """Cut on S1's grid (0.005, or 0.010 when coarse), the face reads S1's checked depth
    everywhere S2 prints it, re-shown on S2's 0.005 grid without moving."""
    _, report, html = traveler(
        plan(tmp_path, coarse=coarse), tmp_path / "out", setup=SYNTHETIC_KERNEL
    )
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    (cut,) = findings["coordinates", "S1"]["numbers"]["operations"]
    face_z = cut["dro_to_z"]
    # The face is cut where the DRO stops: rounded up, never deeper, off the authored Z.
    assert (cut["to_z"], face_z) == (NOMINAL, checked)
    text = printed(html)
    surface, setting = compact_datum(html, "S2", "target")
    assert surface == face_z
    row = evaluated_zero(report, "S2")
    assert row["paper_mm"] == 0.05
    assert setting == pytest.approx(face_z + row["paper_mm"])
    first = evaluated_zero(report, "S1")
    assert first["axis_set"] == first["paper_mm"]
    first_zero_example(html, "S1", first, 0.0)
    endpoint_text = endpoint_cell(html, face_z)
    entry, tip, exit_face = map(
        float,
        re.search(
            r"Z (-?\d+(?:\.\d+)?) → (-?\d+(?:\.\d+)?)[;\s]+breaks through at (-?\d+(?:\.\d+)?)",
            endpoint_text,
        ).groups(),
    )
    (endpoint,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]
    assert entry == endpoint["dro_entry_z"] == face_z
    # The drill works from the stock bottom it exits, as S2 prints it, to a DRO tip on
    # the grid no deeper than the worked tip.
    assert exit_face == -10.0
    assert on_grid(tip) and endpoint["tip_z"] <= tip < endpoint["tip_z"] + STEP
    assert "-2.278" not in text and (not coarse or "-2.275" not in text)


def test_later_setup_rejects_raw_touch_edge_on_the_wrong_grid(tmp_path):
    """Legacy declared bounds are not native-plane credit for a different DRO step."""
    _, report, _ = traveler(
        plan(tmp_path, coarse=True, touch_edge=NOMINAL),
        tmp_path / "out",
        setup=SYNTHETIC_KERNEL,
    )
    row = next(
        row for row in report["findings"] if (row["rule"], row["subject"]) == ("zero_check", "S2")
    )
    assert row["status"] == "error"
    mismatch = re.search(
        r"uses edge (-?\d+(?:\.\d+)?) \(DRO Z (-?\d+(?:\.\d+)?)\); "
        r"the face stands at (-?\d+(?:\.\d+)?)",
        row["message"],
    )
    assert mismatch is not None
    assert tuple(map(float, mismatch.groups())) == (NOMINAL, -2.275, -2.27)


def test_top_zero_after_an_op_is_the_top_that_op_left(tmp_path):
    """A top zero picked up after op 10 is on the face op 10 cut, not the incoming top
    and not the deeper face op 20 cuts later."""
    operations = ZERO.format("top", "after_op = 10\n") + face(10, NOMINAL) + face(20, -3.0)
    path = bundle(tmp_path, FEATURES.split("[features.hole]")[0], operations)
    _, report, html = traveler(path, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    surface, setting = compact_datum(html, "S1", "top")
    assert surface == -2.275
    row = evaluated_zero(report, "S1")
    assert row["paper_mm"] == 0.05
    assert setting == pytest.approx(surface + row["paper_mm"])
    first_zero_example(html, "S1", row, surface)


@pytest.fixture
def fresh_paper_top_projection(monkeypatch):
    """Evaluated D1-style settings whose unnamed incoming lineage has no surface Z.

    Keep the projection branch isolated from native geometry: these are already
    evaluated zero-check facts, not evidence invented by the presentation layer.
    """
    recipe = mill_zero(
        {
            "face": "top",
            "method": "paper",
            "edge_mm": 0.0,
            "paper_mm": 0.0508,
            "tool": "centre/1",
            "holder": "drill-chuck",
            "check_jog_mm": 6.35,
        },
        retouch_after=[10],
    )
    recipe = {"z": recipe["z"], "tool_touches": []}
    data = tool_change_bundle(
        "mill",
        recipe,
        [
            op(10, "spot", "hole", "centre/1", holder="drill-chuck"),
            op(20, "drill", "hole", "drill", holder="drill-chuck"),
        ],
        {"top_z": 0.0, "bottom_z": -12.7},
    )
    data.plan["dro"]["direction"] = {"x": "right", "y": "away", "z": "up"}
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(0.0001)
    data.inventory["holders"] = {"drill-chuck": {"kind": "drill_chuck"}}
    numbers = {
        "axes": {
            "z": {
                "face": "top",
                "method": "paper",
                "tool": "centre/1",
                "holder": "drill-chuck",
                "edge_mm": 0.0,
                "paper_mm": 0.0508,
                "axis_set": 0.0508,
                "axis_set_status": "computed",
                "sign": 1,
                "jog_mm": 6.35,
                "check_reading": 6.4008,
                "mirrored_reading": -6.2992,
            }
        },
        "retouch": [
            {
                "op": 10,
                "next_op": 20,
                "next_tool": "drill",
                "tool_change": True,
                "top_z": 0.0,
                "paper_mm": 0.0508,
                "axis_set": 0.0508,
            }
        ],
    }
    sheet = _Traveler(
        data,
        [Finding("zero_check", "S1", "pass", numbers, [], "Evaluated fresh paper-top zero.")],
        {},
        None,
    )
    # The real partition route has unknown operative lineage. Isolate that
    # condition without coupling the public-output contract to a helper's shape.
    monkeypatch.setattr(sheet, "datum_z", lambda *args, **kwargs: "unknown")
    monkeypatch.setattr(sheet, "surface_z", lambda *args, **kwargs: "unknown")
    tools = {("tools", "centre/1"): "T1 centre drill", ("tools", "drill"): "T2 drill"}
    return sheet, data.plan["setups"][0], numbers, tools


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_fresh_paper_top_keeps_bound_evaluated_zero_without_lineage_debt(
    fresh_paper_top_projection, detail
):
    sheet, setup, numbers, tools = fresh_paper_top_projection
    sheet.detail = detail

    html = sheet.dro(setup, tools)

    assert sheet.producer_decisions.get("S1", []) == []
    if detail == "pedantic":
        assert zero(printed(html), "top") == pytest.approx(
            (0.0, 0.0508, 0.0508, 6.35, 6.4008, -6.2992)
        )
    else:
        (surface,) = re.findall(r"\btop; Z(-?\d+(?:\.\d+)?)(?![\d.])", printed(html))
        assert float(surface) == 0.0
        assert "Z?" not in printed(html)
    assert numbers["axes"]["z"]["axis_set"] == 0.0508


@pytest.mark.parametrize(
    "field,value",
    [
        ("axis_set", None),
        ("axis_set", "unknown"),
        ("axis_set_status", "unknown"),
        ("tool", "drill"),
        ("tool", "unknown"),
        ("holder", "another-chuck"),
        ("holder", "unknown"),
        ("face", "another-face"),
        ("method", "touch"),
        ("edge_mm", "unknown"),
        ("after_op", 20),
    ],
)
def test_fresh_paper_top_does_not_borrow_missing_or_misbound_zero(
    fresh_paper_top_projection, field, value
):
    sheet, setup, numbers, tools = fresh_paper_top_projection
    if value is None:
        del numbers["axes"]["z"][field]
    else:
        numbers["axes"]["z"][field] = value

    html = sheet.dro(setup, tools)

    assert zero_rows(html)["Z"][1] == "?"
    decisions = sheet.producer_decisions["S1"]
    assert any(
        (decision.source, decision.status, decision.scope, decision.kind)
        == ("zero_check", "unknown", "S1:z", "block")
        and "Axis Set" in decision.text
        for decision in decisions
    )


def test_fresh_paper_top_retouch_keeps_bound_evaluated_setting(fresh_paper_top_projection):
    sheet, setup, _, tools = fresh_paper_top_projection

    html = sheet.dro(setup, tools)

    (line,) = [line for line in dro_paragraphs(html) if line.startswith("After op 10")]
    assert "install T2 drill for op 20" in line
    match = re.search(
        r"touch the top \(Z (-?\d+(?:\.\d+)?)\) with "
        r"(\d+(?:\.\d+)?) paper → Axis Set Z (-?\d+(?:\.\d+)?)",
        line,
    )
    assert match is not None
    assert tuple(map(float, match.groups())) == (0.0, 0.0508, 0.0508)
    assert sheet.producer_decisions.get("S1", []) == []


@pytest.mark.parametrize(
    "debt",
    [
        "missing-setting",
        "unknown-setting",
        "unknown-top",
        "wrong-source-op",
        "wrong-next-op",
        "wrong-next-tool",
        "wrong-next-holder",
        "unlisted-existing-source-op",
        "skipped-next-op",
    ],
)
def test_fresh_paper_top_retouch_does_not_borrow_missing_or_misbound_setting(
    fresh_paper_top_projection, debt
):
    sheet, setup, numbers, tools = fresh_paper_top_projection
    (record,) = numbers["retouch"]
    if debt == "missing-setting":
        del record["axis_set"]
    elif debt == "unknown-setting":
        record["axis_set"] = "unknown"
    elif debt == "unknown-top":
        record["top_z"] = "unknown"
    elif debt == "wrong-source-op":
        record["op"] = 99
    elif debt == "wrong-next-op":
        record["next_op"] = 99
    elif debt == "wrong-next-tool":
        record["next_tool"] = "centre/1"
    elif debt in {"unlisted-existing-source-op", "skipped-next-op"}:
        setup["ops"].append(op(30, "drill", "hole", "drill", holder="drill-chuck"))
        record["next_op"] = 30
        if debt == "unlisted-existing-source-op":
            record["op"] = 20
    else:
        setup["ops"][1]["holder"] = "another-chuck"

    html = sheet.dro(setup, tools)

    (line,) = [line for line in dro_paragraphs(html) if line.startswith("After op")]
    assert "Axis Set Z ?" in line
    assert "Axis Set Z 0.0508" not in line


@pytest.fixture
def manual_tap_endpoint_projection(monkeypatch):
    operation = op(30, "hand_tap", "hole", "drill")
    data = tool_change_bundle("mill", {}, [operation], {"top_z": 0.0})
    setup = data.plan["setups"][0]
    setup["id"] = "D1"
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(0.0001)
    endpoint = {
        "depth_scale": "manual",
        "entry_z": 0.0,
        "tip_z": -26.035,
        "depth_mm": 26.035,
        "dro_entry_z": None,
        "dro_tip_z": None,
        "dro_depth_mm": None,
    }
    sheet = _Traveler(data, [], {}, None)
    monkeypatch.setattr(sheet, "endpoint", lambda *args: endpoint)
    return sheet, setup, operation, endpoint


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_manual_tap_prints_checked_hand_depth_not_null_spindle_dro(
    manual_tap_endpoint_projection, detail
):
    sheet, setup, operation, endpoint = manual_tap_endpoint_projection
    sheet.detail = detail

    parts = sheet.tip(setup, operation)

    (line,) = parts
    wording = "from touching the top" if detail == "pedantic" else "below top"
    match = re.fullmatch(rf"hand depth (\d+(?:\.\d+)?) {wording}", line)
    assert match is not None
    assert float(match[1]) == 26.035
    assert all(not hasattr(part, "source") for part in parts)
    assert all(endpoint[key] is None for key in ("dro_entry_z", "dro_tip_z", "dro_depth_mm"))
    assert sheet.producer_decisions.get("D1", []) == []


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
@pytest.mark.parametrize("field", ["entry_z", "tip_z", "depth_mm"])
@pytest.mark.parametrize("state", ["missing", "unknown"])
def test_manual_tap_missing_native_endpoint_keeps_typed_depth_debt(
    manual_tap_endpoint_projection, detail, field, state
):
    sheet, setup, operation, endpoint = manual_tap_endpoint_projection
    sheet.detail = detail
    if state == "missing":
        del endpoint[field]
    else:
        endpoint[field] = "unknown"

    parts = sheet.tip(setup, operation)

    assert parts[0] == "hand depth not set"
    (_, debt) = parts
    assert (debt.source, debt.status, debt.scope, debt.kind) == (
        "blind_depth",
        "unknown",
        "D1:30",
        "block",
    )
    assert "26.035" not in " ".join(parts)
    assert "Z ?" not in " ".join(parts)


@pytest.mark.parametrize("detour", [NOMINAL - 1.0, NOMINAL])
def test_pickup_follows_the_stock_it_received(tmp_path, detour):
    """S3 receives S1's stock, not S2's refaced one: S2's cut, deeper or to the same
    nominal on its finer grid, is in another branch. S3's arrival, zero and entry are
    S1's checked face on S1's 0.010 grid, whatever S2 checked."""
    path = plan(tmp_path, coarse=True, detour=detour)
    _, report, html = traveler(path, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    for sid in ("S2", "S3"):
        surface, setting = compact_datum(html, sid, "target")
        assert surface == -2.27
        row = evaluated_zero(report, sid)
        assert row["paper_mm"] == 0.05
        assert setting == pytest.approx(surface + row["paper_mm"])
    endpoints = {
        row["setup"]: row
        for finding in report["findings"]
        if (finding["rule"], finding["subject"]) == ("blind_depth", "hole")
        for row in finding["numbers"]["endpoints"]
    }
    assert endpoints["S3"]["dro_entry_z"] == -2.27


FRAME = {"origin": [0.0] * 3, "x": [1.0, 0, 0], "y": [0, 1.0, 0], "z": [0, 0, 1.0]}


def turned_from(tmp_path, cut, shaft_xy):
    """S1 on a 0.010 mill ``cut``-s (finish_face ``target``, x 0..20 y 0..10, or
    finish_pocket ``other``, x/y 10..20) to Z -2.27825; L2, a 0.005 lathe receiving S1's
    stock in the same frame, turns ``shaft`` (X/Y footprint ``shaft_xy``, or none) from
    that Z. Returns L2's (start Z of the op row, feature map text)."""
    plane = {"kind": "plane", "frame": "model", "requirements": []}
    shaft = {"kind": "shaft", "frame": "model", "dia": 6.0, "z_mm": [NOMINAL, -10.0]}
    if shaft_xy:
        shaft["bounds"] = {"x": shaft_xy, "y": shaft_xy, "z": [-10.0, NOMINAL]}
    features = {
        "target": {**plane, "bounds": {"x": [0.0, 20.0], "y": [0.0, 10.0], "z": [NOMINAL, 0.0]}},
        "other": {**plane, "bounds": {"x": [10.0, 20.0], "y": [10.0, 20.0], "z": [NOMINAL, 0.0]}},
        "shaft": {**shaft, "requirements": []},
    }
    do, feature = cut
    setups = [
        {
            "id": "S1",
            "stock_in": "stock",
            "machine": "coarse",
            "frame": "A",
            "stock_state": {"top_z": 0.0},
            "ops": [{"op": 10, "do": do, "feature": feature, "tool": "cutter", "to_z": NOMINAL}],
        },
        {
            "id": "L2",
            "stock_in": "S1",
            "machine": "fine",
            "frame": "A",
            "stock_state": {"top_z": NOMINAL},
            "ops": [
                {
                    "op": 10,
                    "do": "finish_turn",
                    "feature": "shaft",
                    "tool": "cutter",
                    "z_from": NOMINAL,
                    "z_to": -10.0,
                }
            ],
        },
    ]
    direction = {"x": "right", "y": "away", "z": "up"}
    dro = {"controller": "EL400", "mode": "abs", "radius_mode": False, "direction": direction}
    machines = {
        "coarse": {"kind": "mill", "resolution_mm": measured(2 * STEP)},
        "fine": {"kind": "lathe", "resolution_mm": measured(STEP)},
    }
    tools = {"cutter": {"kind": "endmill", "dia_mm": 6.0, "nose_radius_mm": 0.0}}
    frames = {"A": {**FRAME, "binding": "nominal"}, "model": {**FRAME, "binding": "nominal"}}
    bundle = Bundle(
        Plan.model_validate(
            {"part": "p", "features": "features.toml", "dro": dro, "setups": setups}
        ).model_dump(exclude_unset=True),
        Features.model_validate(
            {"part": "p", "units": "mm", "frames": frames, "features": features}
        ).model_dump(exclude_unset=True),
        Inventory.model_validate({"machines": machines, "tools": tools}).model_dump(
            exclude_unset=True
        ),
        {},
        {},
        {},
        {},
        Path(tmp_path),
    )
    findings = [
        *coordinates.evaluate(bundle),
        *tip_endpoints.evaluate(bundle),
        *zero_recipe_rule.evaluate(bundle),
    ]
    sheet = _Traveler(bundle, findings, {}, {})
    lathe = bundle.plan["setups"][1]
    sheet.setup = lathe
    (row,) = sheet.tip(lathe, lathe["ops"][0])
    match = re.fullmatch(r"Z (-?\d+(?:\.\d+)?) → (-?\d+(?:\.\d+)?)", row)
    assert match is not None
    start, end = map(float, match.groups())
    assert end == -10.0
    # The lathe map prints the drawing Ø limits (here none) apart from the turn-to Ø.
    mapped = re.search(
        r"\|shaft\|+[^|]*\|+Ø6(?:\.0+)?\|+(-?\d+(?:\.\d+)?)\|+(-?\d+(?:\.\d+)?)\|",
        printed(sheet.feature_map(lathe)),
    )
    assert mapped is not None
    assert float(mapped[2]) == -10.0
    mapped = float(mapped[1])
    return start, mapped


@pytest.mark.parametrize(
    "cut,shaft_xy,printed",
    [
        (("finish_face", "target"), [2.0, 8.0], "-2.270"),
        (("finish_pocket", "other"), [2.0, 8.0], "-2.275"),
        # Half the shaft lies outside the face's x/y 0..20 x 0..10: overlap is not cover.
        (("finish_face", "target"), [-3.0, 3.0], "-2.275"),
        (("finish_face", "target"), None, "-2.275"),
    ],
)
def test_turned_start_links_only_a_cut_that_covers_it(tmp_path, cut, shaft_xy, printed):
    """A turned surface starts on S1's coarse as-cut -2.270 only when S1's cut covers its
    X/Y footprint; a disjoint pocket at the same nominal Z, or a shaft with no footprint
    to prove it, starts on the nominal as L2's 0.005 DRO shows it. Its op row and the
    feature map print the same value."""
    assert turned_from(tmp_path, cut, shaft_xy) == (float(printed), float(printed))


@pytest.mark.parametrize("exit_mm,stopped", [(0.0, True), (STEP, False)])
def test_rounded_up_through_tip_that_stops_short_is_a_stop(tmp_path, exit_mm, stopped):
    """A DRO tip rounded up off a zero break-through stops the drill point short of the
    exit face, so the drill row stops; one grid step of authored break-through clears it."""
    _, _, html = traveler(plan(tmp_path, exit_mm), tmp_path / "out", setup=SYNTHETIC_KERNEL)
    cell = endpoint_cell(html, -2.275)
    assert ("STOP" in cell) is stopped


@pytest.mark.parametrize(
    "do,drilled,depth,stopped",
    [
        ("drill", BLIND, [BLIND, 20.0], True),
        ("drill", BLIND, [BLIND - STEP, 20.0], False),
        ("drill", BLIND, 20.0, True),
        ("tap", 3.001, [3.001, 3.001], True),
        ("tap", 3.001, [3.0, 3.001], False),
    ],
)
def test_rounded_up_depth_outside_its_depth_band_is_a_stop(tmp_path, do, drilled, depth, stopped):
    """Rounded up, the DRO tip leaves a blind hole or thread shallower than authored.
    Below the band's lower end is a STOP; a band that reaches it clears it; a bare upper
    limit leaves the lower end unknown, and unknown is not a pass."""
    path = plan(tmp_path, depth=depth, do=do, drilled=drilled)
    _, report, html = traveler(path, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (endpoint,) = [
        row
        for finding in report["findings"]
        if (finding["rule"], finding["subject"]) == ("blind_depth", "hole")
        for row in finding["numbers"]["endpoints"]
    ]
    shown = endpoint["dro_depth_mm"]
    assert drilled - STEP < shown < drilled
    cell = endpoint_cell(html, -2.275)
    (printed_depth,) = re.findall(r"\bdepth (-?\d+(?:\.\d+)?)(?![\d.])", cell)
    assert float(printed_depth) == shown
    assert ("STOP" in cell) is stopped
