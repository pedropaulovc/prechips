"""Each negative control asserts the prescribed stop and its named cause."""

import json
import re
import tomllib

import pytest
from test_cli import SYNTHETIC_KERNEL, copy_examples, rocker_s1_alone, traveler


def finding(report, rule, subject):
    return next(
        row for row in report["findings"] if row["rule"] == rule and row["subject"] == subject
    )


def swap(text, old, new):
    """Apply one explicit scratch mutation; an absent target is a broken control, not a no-op."""
    assert old in text, old
    return text.replace(old, new)


def test_removed_reamer_is_named_inventory_error(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    inventory = examples / "inventory" / "pedro-shop.toml"
    original = inventory.read_text(encoding="utf-8")
    text = plan.read_text(encoding="utf-8")
    reamers = {
        op["tool"]
        for setup in tomllib.loads(text)["setups"]
        for op in setup.get("ops", [])
        if op.get("do") == "ream"
    }
    assert reamers, "the control needs a planned ream op"
    for reamer in reamers:
        text = swap(text, f'tool = "{reamer}"', 'tool = "control-reamer-6.5"')
    plan.write_text(text, encoding="utf-8")
    known = (
        '\n[tools."control-reamer-6.5"]\nkind = "reamer"\nverify = false\n'
        'dia_mm = 6.5\nshank_mm = 6.5\nlead_mm = 1.0\nunits = "mm"\n'
    )
    inventory.write_text(original + known, encoding="utf-8")
    _, present, _ = traveler(plan, tmp_path / "present", setup=SYNTHETIC_KERNEL)
    assert finding(present, "tool_resolves", "control-reamer-6.5")["status"] == "pass"
    inventory.write_text(original, encoding="utf-8")
    result, absent, html = traveler(plan, tmp_path / "absent", setup=SYNTHETIC_KERNEL)
    assert result.returncode == 2, result.stderr
    row = finding(absent, "tool_resolves", "control-reamer-6.5")
    assert row["status"] == "error"
    assert "reamer" in row["message"].lower()
    assert "reamer" in (html + result.stderr).lower()


def test_reversed_dro_direction_swaps_expected_and_mirrored_readings(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    authored = tomllib.loads(text)
    assert authored["dro"]["direction"]["x"] == "right", "the control reverses an authored +X DRO"
    s1 = next(setup for setup in authored["setups"] if setup["id"] == "S1")
    jog = s1["zero"]["x"]["check_jog_mm"]
    _, baseline, _ = traveler(plan, tmp_path / "baseline", setup=SYNTHETIC_KERNEL)
    row = finding(baseline, "zero_check", "S1")
    assert row["status"] == "pass", row
    before = row["numbers"]["axes"]["x"]
    assert before["check_reading"] == pytest.approx(before["axis_set"] + jog)
    assert before["mirrored_reading"] == pytest.approx(before["axis_set"] - jog)
    reversed_text, count = re.subn(r'(?m)^x = "right"', 'x = "left"', text, count=1)
    authored["dro"]["direction"]["x"] = "left"
    assert count == 1 and tomllib.loads(reversed_text) == authored, "only the DRO X sense flips"
    plan.write_text(reversed_text, encoding="utf-8")
    result, reversed_report, _ = traveler(plan, tmp_path / "reversed", setup=SYNTHETIC_KERNEL)
    row = finding(reversed_report, "zero_check", "S1")
    after = row["numbers"]["axes"]["x"]
    # The touch-off is unchanged; only the reading the authored +X jog produces reverses.
    assert after["axis_set"] == pytest.approx(before["axis_set"])
    assert after["check_reading"] == pytest.approx(after["axis_set"] - jog)
    assert after["mirrored_reading"] == pytest.approx(after["axis_set"] + jog)
    assert after["check_reading"] == pytest.approx(before["mirrored_reading"])
    assert after["mirrored_reading"] == pytest.approx(before["check_reading"])
    assert row["status"] == "error"
    assert result.returncode == 2


# A whole key/value line, including a multiline basic or literal string value or an array
# of strings over one or more lines.
POSITION_CHECK = re.compile(
    r'(?ms)^position_dia = (?:""".*?"""|\'\'\'.*?\'\'\''
    r'|\[(?:"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'|[^\]"\'])*\]|[^\n]*)[^\n]*\n'
)
# A whole set-up sketch table of the position check: its header and every line up to the
# next table header.
POSITION_VIEW = re.compile(
    r"(?ms)^\[\[setups\.ops\.inspection_views\.position_dia\]\]\n.*?(?=^\[|\Z)"
)


def test_removed_position_check_is_named_error_not_size_coverage(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    _, baseline, _ = traveler(plan, tmp_path / "baseline", setup=SYNTHETIC_KERNEL)
    # Remove each position check together with its inspection method and the set-up
    # sketches that illustrate that method; nothing else changes.
    expected = tomllib.loads(text)
    features = set()
    for setup in expected["setups"]:
        for op in setup.get("ops", []):
            checks = op.get("checks")
            if isinstance(checks, dict) and checks.pop("position_dia", None) is not None:
                features.add(op["feature"])
            methods = op.get("inspection_methods")
            if isinstance(methods, dict):
                methods.pop("position_dia", None)
            views = op.get("inspection_views")
            if isinstance(views, dict):
                views.pop("position_dia", None)
                if not views:
                    del op["inspection_views"]
    assert features, "the control needs a planned position check"
    stripped = POSITION_VIEW.sub("", POSITION_CHECK.sub("", text))
    assert tomllib.loads(stripped) == expected
    plan.write_text(stripped, encoding="utf-8")
    result, report, _ = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    assert result.returncode == 2, result.stderr
    for feature in sorted(features):
        subject = f"{feature}:position_dia"
        assert "op" in finding(baseline, "inspection", subject)["numbers"]
        row = finding(report, "inspection", subject)
        assert row["status"] == "error", row
        assert "op" not in row["numbers"] and row["numbers"]["gauge"] == "unknown"
        # The feature's own size checks still exist and are untouched; they cannot cover position.
        sizes = {
            other["subject"]: other["status"]
            for other in baseline["findings"]
            if other["rule"] == "inspection"
            and other["subject"].startswith(f"{feature}:")
            and other["subject"] != subject
            and "op" in other["numbers"]
        }
        assert sizes, f"the control needs a {feature} size check that could substitute"
        for size, status in sizes.items():
            assert finding(report, "inspection", size)["status"] == status


def clean_inspection_bundle(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    prefix = rocker_s1_alone(plan.read_text(encoding="utf-8"))
    prefix, schedules = re.subn(r"(?m)^retouch_after = .*$", "retouch_after = []", prefix)
    assert schedules == 1, "the clean bundle pins the copied S1 retouch schedule"
    plan.write_text(
        prefix + '\n[[setups.ops]]\nop = 10\ndo = "inspect"\nfeature = "hub_faces"\n'
        'checks = { dia = "control-micrometer", length = "control-micrometer" }\n',
        encoding="utf-8",
    )
    features = plan.with_name("features.toml")
    features.write_text(
        'part = "rocker-arm"\nunits = "mm"\nprecision = 2\nstep_sha256 = "unknown"\n'
        "[frames.A]\norigin = [0.0, 0.0, 0.0]\nx = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\n"
        "z = [0.0, 0.0, 1.0]\n"
        '[features.hub_faces]\nkind = "boss"\nframe = "A"\nat = [0.0, 0.0, 0.0]\n'
        'dia = [6.50, 6.53]\nlength = [5.0, 6.0]\nrequirements = ["dia", "length"]\n',
        encoding="utf-8",
    )
    inventory = examples / "inventory" / "pedro-shop.toml"
    with inventory.open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[gauges.control-micrometer]\nkind = "micrometer"\nrange_mm = [0.0, 25.0]\n'
            "resolution_mm = 0.001\nverify = false\n"
        )
    (examples / "shop-policy.toml").write_text(
        '[required]\ninspection = "toleranced_features"\n', encoding="utf-8"
    )
    return plan


def test_one_unknown_tolerance_blocks_otherwise_clean_policy(tmp_path, freecad_kernel):
    plan = clean_inspection_bundle(tmp_path)
    result, baseline, _ = traveler(plan, tmp_path / "known")
    assert result.returncode == 0, result.stderr
    assert finding(baseline, "inspection", "hub_faces:dia")["status"] == "pass"
    features = plan.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8").replace("dia = [6.50, 6.53]", 'dia = "unknown"'),
        encoding="utf-8",
    )
    result, report, html = traveler(plan, tmp_path / "unknown")
    assert result.returncode == 4, result.stderr
    row = finding(report, "inspection", "hub_faces:dia")
    assert row["status"] == "unknown"
    assert row["numbers"]["limits"] == "unknown"
    assert finding(report, "inspection", "hub_faces:length")["status"] == "pass"
    assert not any(row["status"] == "error" for row in report["findings"])
    assert "PLANNED" in html
    assert "hub_faces" in (html + result.stderr)


def test_approval_stales_when_feature_input_changes(tmp_path, freecad_kernel):
    plan = clean_inspection_bundle(tmp_path)
    result, baseline, _ = traveler(plan, tmp_path / "baseline")
    assert result.returncode == 0, result.stderr
    approval = tmp_path / "approvals.toml"
    lines = [
        f'hash = "{baseline["hash"]}"',
        'first_article = "Control first article accepted"',
    ]
    for kind, record in baseline["inputs"].items():
        lines.extend(
            [
                f'[inputs."{kind}"]',
                f"path = {json.dumps(record['path'])}",
                f'sha256 = "{record["sha256"]}"',
            ]
        )
    approval.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result, _, html = traveler(plan, tmp_path / "approved", "--approval", approval)
    assert result.returncode == 0, result.stderr
    assert "CHECKED" in html
    assert "PLANNED" not in html
    features = plan.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8").replace("[6.50, 6.53]", "[6.50, 6.54]"),
        encoding="utf-8",
    )
    result, report, html = traveler(plan, tmp_path / "stale", "--approval", approval)
    assert result.returncode == 0, result.stderr
    assert report["hash"] != baseline["hash"]
    assert "PLANNED" in html
    assert "CHECKED" not in html
    assert "features" in result.stderr.lower()
    assert "features" in html.lower()


@pytest.mark.parametrize(
    ("state", "declaration", "expected_exit"),
    [
        ("absent", "", 4),
        ("unknown", 'required = "unknown"\n', 4),
        ("empty", "[required]\n", 0),
    ],
)
def test_missing_required_policy_is_unknown_not_empty(
    tmp_path, request, state, declaration, expected_exit
):
    if expected_exit == 0:
        request.getfixturevalue("freecad_kernel")
    plan = clean_inspection_bundle(tmp_path)
    policy = plan.parent.parent / "shop-policy.toml"
    policy.write_text("revision = 1\n" + declaration + "[numbers]\n", encoding="utf-8")
    result, report, html = traveler(plan, tmp_path / "out")
    unresolved = [row for row in report["findings"] if row["status"] == "unknown"]
    assert result.returncode == expected_exit, {
        "state": state,
        "verification": report["verification"],
        "unknown_count": len(unresolved),
    }
    if state == "empty":
        assert report["verification"] == "checked"
        assert unresolved  # Nonrequired unknowns do not override a known empty policy.
    else:
        assert report["verification"] != "checked"
        assert finding(report, "required_policy", "*")["status"] == "unknown"
        assert "PLANNED" in html


@pytest.mark.parametrize(
    ("state", "declaration", "expected_exit"),
    [
        ("absent", "", 4),
        ("unknown", 'requirements = "unknown"\n', 4),
        ("empty", "requirements = []\n", 0),
    ],
)
def test_missing_requirements_are_unknown_not_known_absence(
    tmp_path, request, state, declaration, expected_exit
):
    if expected_exit == 0:
        request.getfixturevalue("freecad_kernel")
    plan = clean_inspection_bundle(tmp_path)
    # This control varies the requirement declaration, not an invalid plan check.
    # Checks cannot claim an acceptance requirement the selected feature lacks.
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            'checks = { dia = "control-micrometer", length = "control-micrometer" }\n', ""
        ),
        encoding="utf-8",
    )
    features = plan.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8").replace(
            'requirements = ["dia", "length"]\n', declaration
        ),
        encoding="utf-8",
    )
    result, report, html = traveler(plan, tmp_path / "out")
    rows = [row for row in report["findings"] if row["rule"] == "inspection"]
    assert result.returncode == expected_exit, {
        "state": state,
        "verification": report["verification"],
        "inspection": rows,
    }
    if state == "empty":
        assert report["verification"] == "checked"
        assert finding(report, "inspection", "hub_faces")["status"] == "not_applicable"
    else:
        assert report["verification"] != "checked"
        assert finding(report, "inspection", "hub_faces:unknown")["status"] == "unknown"
        assert not any(row["status"] == "not_applicable" for row in rows)
        assert "PLANNED" in html


@pytest.mark.parametrize(
    ("state", "declaration", "expected_exit", "expected_retouch"),
    [
        ("absent", "", 4, []),
        ("unknown", 'retouch_after = "unknown"\n', 4, []),
        ("empty", "retouch_after = []\n", 0, []),
        ("listed", "retouch_after = [10, 20]\n", 0, [10, 20]),
    ],
)
def test_missing_retouch_schedule_is_unknown_after_facing(
    tmp_path, request, state, declaration, expected_exit, expected_retouch
):
    if expected_exit == 0:
        request.getfixturevalue("freecad_kernel")
    plan = clean_inspection_bundle(tmp_path)
    prefix = plan.read_text(encoding="utf-8").split("[[setups.ops]]", 1)[0]
    # S1 keeps its authored hold; its stock top and whole zero recipe are synthetic, so the
    # schedule control never depends on the example's tool ids or facing order.
    head, *zeros = re.split(r"(?m)^\[setups\.zero\][^\n]*\n", prefix)
    assert len(zeros) == 1, "the control replaces the copied S1 [setups.zero] table"
    for key, value in [("top_feature", '"hub_faces"'), ("top_z", "0.5")]:
        head, count = re.subn(rf"(?m)^{key} = .*$", f"{key} = {value}", head)
        assert count == 1, f"the control needs the copied S1 stock_state {key}"
    finders = "".join(
        f'\n[setups.zero.{axis}]\nedge = "control_{axis}_edge"\nfrom = "-{axis}"\n'
        'tool = "control-finder"\nholder = "r8-collets-lms-4860/3-8in"\n'
        f"edge_mm = {edge}\ncheck_jog_mm = 10.0\n"
        for axis, edge in [("x", -170.0), ("y", -28.0)]
    )
    prefix = (
        head
        + "[setups.zero]\ntool_touches = []\n"
        + finders
        + '\n[setups.zero.z]\nface = "top"\nmethod = "paper"\npaper_mm = 0.05\n'
        'tool = "control-face"\ncheck_jog_mm = 10.0\n' + declaration
    )
    ops = "".join(
        f'\n[[setups.ops]]\nop = {op}\ndo = "face"\nfeature = "hub_faces"\n'
        f'tool = "{tool}"\nholder = "r8-collets-lms-4860/3-8in"\n'
        'to_z = 0.0\ndirection = "conventional"\n'
        for op, tool in [(10, "control-face"), (20, "control-second"), (30, "control-third")]
    )
    plan.write_text(prefix + ops, encoding="utf-8")
    features = plan.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8")
        .replace('requirements = ["dia", "length"]', "requirements = []")
        .replace("z = [0.0, 0.0, 1.0]", 'z = [0.0, 0.0, 1.0]\nbinding = "control-measured"'),
        encoding="utf-8",
    )
    inventory = plan.parent.parent / "inventory" / "pedro-shop.toml"
    finder = 'finder_type = "mechanical"\nrpm_range = [750, 1500]\n'
    with inventory.open("a", encoding="utf-8") as stream:
        for tool, kind, extra in [
            ("control-finder", "edge_finder", finder),
            ("control-face", "endmill", ""),
            ("control-second", "endmill", ""),
            ("control-third", "endmill", ""),
        ]:
            stream.write(
                f'\n[tools.{tool}]\nkind = "{kind}"\nverify = false\n'
                f'dia_mm = 6.0\nshank_mm = 9.525\nunits = "mm"\n{extra}'
            )
    (plan.parent.parent / "shop-policy.toml").write_text(
        '[required]\nzero_check = "setups"\n', encoding="utf-8"
    )
    result, report, html = traveler(plan, tmp_path / "out")
    row = finding(report, "zero_check", "S1")
    assert row["numbers"]["axes"]["z"]["axis_set"] == pytest.approx(0.55)
    assert [touch["op"] for touch in row["numbers"]["retouch"]] == expected_retouch
    assert result.returncode == expected_exit, {
        "state": state,
        "verification": report["verification"],
        "zero_check": row,
    }
    if expected_exit:
        assert row["status"] == "unknown"
        assert report["verification"] != "checked"
        assert "PLANNED" in html
    else:
        assert row["status"] == "pass"
        assert report["verification"] == "checked"
        for touch in row["numbers"]["retouch"]:
            assert touch["top_z"] == pytest.approx(0.0)
            assert touch["axis_set"] == pytest.approx(0.05)
