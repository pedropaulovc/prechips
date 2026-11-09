import base64
import subprocess
from html.parser import HTMLParser

import pytest

PLAN = """\
title = "Bracket <trial>"
part = "B&1"
revision = "A"
material = "Aluminium"
stock = "20 × 10 × 40 mm"
note = "Use the drawing's limits."

[[tools]]
id = "internal-mill-id"
description = "6 mm end mill"

[[setups]]
title = "Face stock"
machine = "Manual mill"
machine_kind = "other"
holding = "Vise on parallels"
datum = "Top face; left end"
inspection = ["Check thickness & squareness."]

[[setups.operations]]
tool = "internal-mill-id"
instruction = "Face to thickness.\\nKeep < 0.2 mm finishing allowance."
rpm = 1200
feed = "Hand feed, about 50 mm/min"
inspection = "Measure at both ends."
"""

SECOND_SETUP = """
[[setups]]
title = "Drill pattern"
machine = "Manual mill"
machine_kind = "other"

[[setups.operations]]
instruction = "Locate the pattern."

[setups.operations.table]
columns = ["Feature", "X", "Y"]
rows = [["Hole <A>", "12.50", "-3.25"], ["Hole B", "25.00", "0.00\\n4.00"]]
"""


class OperatorText(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_body = False
        self.parts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body and data.strip():
            self.parts.append(data.strip())


def run_cli(tmp_path, text, *options):
    plan = tmp_path / "plan.toml"
    out = tmp_path / "out" / "traveler.html"
    plan.write_text(text, encoding="utf-8")
    result = subprocess.run(
        ["prechips", "traveler", str(plan), "--out", str(out), *options],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result, out


def stock_free_profile(tmp_path, *, diagrams=False):
    """Keep literal-plan rendering tests independent of optional enforcement."""
    profile = tmp_path / "rendering.toml"
    names = '["setup_diagrams"]' if diagrams else "[]"
    profile.write_text(
        f'name = "Rendering only"\nfeatures = {names}\nenforce = {names}\n',
        encoding="utf-8",
    )
    return str(profile)


def test_real_cli_renders_escaped_operator_content(tmp_path):
    result, out = run_cli(tmp_path, PLAN, "--profile", stock_free_profile(tmp_path))
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    assert "Bracket &lt;trial&gt;" in html
    assert "B&amp;1" in html
    assert "Face to thickness.\nKeep &lt; 0.2 mm" in html
    assert "6 mm end mill" in html
    assert "internal-mill-id" not in html
    assert "1200" in html
    assert "Hand feed, about 50 mm/min" in html
    assert "Measure at both ends." in html
    assert "Check thickness &amp; squareness." in html


def test_numbered_setups_operations_and_authored_table_content(tmp_path):
    text = (
        PLAN.replace(
            'description = "6 mm end mill"',
            'name = "End mill <6>"\ndescription = "6 mm end mill"',
        )
        + SECOND_SETUP
    )
    result, out = run_cli(tmp_path, text, "--profile", stock_free_profile(tmp_path))
    assert result.returncode == 0, result.stderr
    parts = OperatorText(out.read_text(encoding="utf-8")).parts
    assert "Setup 1 — Face stock" in parts
    assert "Setup 2 — Drill pattern" in parts
    assert parts.index("10") < parts.index("20")
    assert "End mill <6>" in parts
    assert "Locate the pattern." in parts
    assert "6 mm end mill" in parts
    assert "Feature" in parts
    assert "Hole <A>" in parts
    assert "12.50" in parts
    assert "-3.25" in parts
    assert "25.00" in parts
    assert "0.00\n4.00" in parts
    assert "Measure at both ends." in parts
    assert "Check thickness & squareness." in parts
    assert "internal-mill-id" not in parts


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('title = "unterminated', "Unterminated string"),
        (PLAN.replace('tool = "internal-mill-id"', 'tool = "missing"'), "unknown tool"),
        (PLAN.replace("rpm = 1200", "rpm = true"), "expected a positive integer"),
        (PLAN.replace('title = "Bracket <trial>"', ""), "plan.title"),
        (
            PLAN.replace(
                'description = "6 mm end mill"',
                'name = ""\ndescription = "6 mm end mill"',
            ),
            "tools[1].name",
        ),
        (
            PLAN
            + SECOND_SETUP.replace(
                '"Hole <A>", "12.50", "-3.25"', '"Hole <A>", "12.50"'
            ),
            "rows matching the columns",
        ),
        (
            PLAN
            + SECOND_SETUP.replace('columns = ["Feature", "X", "Y"]', "columns = []"),
            "column names",
        ),
    ],
)
def test_bad_input_has_useful_error_without_output(tmp_path, text, message):
    result, out = run_cli(tmp_path, text)
    assert result.returncode == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


@pytest.mark.parametrize("quantity", ["0", "-1", "1.5", "2.0", "true"])
def test_pro_rejects_invalid_quantity(tmp_path, quantity):
    text = PLAN + f"\n[parameters]\nquantity = {quantity}\n"
    result, out = run_cli(tmp_path, text, "--profile", "pro")
    assert result.returncode == 2
    assert "parameters.quantity: expected a positive integer" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


def test_literal_plan_accepts_positive_integer_quantity(tmp_path):
    text = (
        PLAN.replace(
            'stock = "20 × 10 × 40 mm"',
            'stock = "{{process.quantity}} blanks, 20 × 10 × 40 mm"',
        )
        + "\n[parameters]\nquantity = 2\n"
    )
    result, out = run_cli(tmp_path, text, "--profile", stock_free_profile(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "2 blanks, 20 × 10 × 40 mm" in out.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "parameter",
    [
        "blank_length_in",
        "blank_width_in",
        "blank_thickness_in",
        "slot_finish_diameter_in",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_pro_rejects_nonpositive_dimensions(tmp_path, parameter, value):
    text = PLAN + f"\n[parameters]\n{parameter} = {value}\n"
    result, out = run_cli(tmp_path, text, "--profile", "pro")
    assert result.returncode == 2
    assert f"parameters.{parameter}: expected a positive number" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


@pytest.mark.parametrize("output_kind", ["input", "hardlink"])
def test_output_cannot_replace_input_plan(tmp_path, output_kind):
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN, encoding="utf-8")
    out = plan
    if output_kind == "hardlink":
        out = tmp_path / "alias.html"
        out.hardlink_to(plan)
    result = subprocess.run(
        ["prechips", "traveler", str(plan), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "output must not overwrite the input plan" in result.stderr
    assert plan.read_text(encoding="utf-8") == PLAN
    assert out.read_text(encoding="utf-8") == PLAN


def with_diagram(text, file="diagrams/setup.svg", alt="Vise & stock <side view>"):
    return text.replace(
        'machine = "Manual mill"',
        f'machine = "Manual mill"\ndiagram = {{ file = "{file}", alt = "{alt}" }}',
    )


def test_stock_free_unillustrated_profile_does_not_read_unused_diagram(tmp_path):
    result, out = run_cli(
        tmp_path,
        with_diagram(PLAN, file="missing.svg"),
        "--profile",
        stock_free_profile(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "<img " not in out.read_text(encoding="utf-8")


def test_required_diagrams_embed_each_setup_before_operations(tmp_path):
    diagrams = tmp_path / "diagrams"
    diagrams.mkdir()
    first = b'<svg xmlns="http://www.w3.org/2000/svg"><text>First</text></svg>'
    second = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Second</text></svg>'
    (diagrams / "setup.svg").write_bytes(first)
    (diagrams / "drill.svg").write_bytes(second)
    text = with_diagram(PLAN) + with_diagram(
        SECOND_SETUP, file="diagrams/drill.svg", alt="Drill pattern"
    )
    result, out = run_cli(
        tmp_path, text, "--profile", stock_free_profile(tmp_path, diagrams=True)
    )
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    first_image = "data:image/svg+xml;base64," + base64.b64encode(first).decode("ascii")
    second_image = "data:image/svg+xml;base64," + base64.b64encode(second).decode(
        "ascii"
    )
    assert html.count("<img ") == 2
    assert html.index(first_image) < html.index("Face to thickness.")
    assert html.index("Setup 2 — Drill pattern") < html.index(second_image)
    assert html.index(second_image) < html.index("Locate the pattern.")
    assert 'alt="Vise &amp; stock &lt;side view&gt;"' in html
    assert "<svg" not in html


@pytest.mark.parametrize("asset", [None, "missing.svg", "invalid.svg"])
def test_required_diagrams_need_usable_asset_for_named_setup(tmp_path, asset):
    (tmp_path / "invalid.svg").write_text("<html/>", encoding="utf-8")
    text = PLAN if asset is None else with_diagram(PLAN, file=asset)
    result, out = run_cli(
        tmp_path, text, "--profile", stock_free_profile(tmp_path, diagrams=True)
    )
    assert result.returncode == 2
    assert "Face stock" in result.stderr
    assert "diagram" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


def test_custom_optional_diagrams_and_plan_relative_paths(tmp_path):
    profile = tmp_path / "optional.toml"
    profile.write_text(
        'name = "Optional pictures"\nfeatures = ["setup_diagrams"]\nenforce = []\n',
        encoding="utf-8",
    )
    result, out = run_cli(tmp_path, PLAN, "--profile", str(profile))
    assert result.returncode == 0, result.stderr
    assert "<img " not in out.read_text(encoding="utf-8")
    diagrams = tmp_path / "diagrams"
    diagrams.mkdir()
    (diagrams / "setup.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8"
    )
    result, out = run_cli(tmp_path, with_diagram(PLAN), "--profile", str(profile))
    assert result.returncode == 0, result.stderr
    assert "<img " in out.read_text(encoding="utf-8")
    out.unlink()
    result, out = run_cli(
        tmp_path, with_diagram(PLAN, file="missing.svg"), "--profile", str(profile)
    )
    assert result.returncode == 2
    assert "Face stock" in result.stderr
    assert not out.exists()


@pytest.mark.parametrize("input_kind", ["profile", "diagram"])
@pytest.mark.parametrize("output_kind", ["input", "hardlink"])
def test_output_cannot_replace_profile_or_used_diagram(
    tmp_path, input_kind, output_kind
):
    profile = stock_free_profile(tmp_path, diagrams=True)
    diagram = tmp_path / "setup.svg"
    diagram.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    plan = tmp_path / "plan.toml"
    plan.write_text(with_diagram(PLAN, file="setup.svg"), encoding="utf-8")
    source = tmp_path / "rendering.toml" if input_kind == "profile" else diagram
    before = source.read_bytes()
    out = source
    if output_kind == "hardlink":
        out = tmp_path / "alias.html"
        out.hardlink_to(source)
    result = subprocess.run(
        [
            "prechips",
            "traveler",
            str(plan),
            "--out",
            str(out),
            "--profile",
            profile,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "output must not overwrite" in result.stderr
    assert source.read_bytes() == before
    assert out.read_bytes() == before


TURNING_PLAN = (
    PLAN.replace(
        'material = "Aluminium"', 'material = "Steel"\nturning_material = "steel_1018"'
    )
    .replace('machine_kind = "other"', 'machine_kind = "lathe"')
    .replace(
        'holding = "Vise on parallels"',
        'turning_support = { kind = "chuck_only", chuck_z_mm = 0.0 }',
    )
    .replace(
        'tool = "internal-mill-id"',
        'cut_kind = "longitudinal_turning"\ntool = "internal-mill-id"',
    )
    + """
[[setups.operations.turning_cuts]]
name = "Body finish"
phase = "finish"
start_z_mm = 1.0
end_z_mm = 2.0
start_diameter_mm = 20.1
end_diameter_mm = 20.0
max_radial_doc_mm = 0.05
feed_mm_rev = 0.05
minimum_diameter_mm = 20.0
"""
)


@pytest.fixture
def run_turning_cli(capsys):
    from prechips.cli import main

    def invoke(tmp_path, text, *options):
        plan = tmp_path / "plan.toml"
        out = tmp_path / "out" / "traveler.html"
        plan.write_text(text, encoding="utf-8")
        args = ["traveler", str(plan), "--out", str(out), *options]
        returncode = main(args)
        captured = capsys.readouterr()
        return (
            subprocess.CompletedProcess(args, returncode, captured.out, captured.err),
            out,
        )

    return invoke


@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_builtin_profiles_enforce_turning_before_output(tmp_path, profile):
    text = TURNING_PLAN + "max_deflection_mm = 1e-20\n"
    result, out = run_cli(
        tmp_path,
        text,
        "--profile",
        profile,
        "--disable-check",
        "stock_fit",
        "--disable-check",
        "setup_diagrams",
    )
    assert result.returncode == 2
    assert "turning_deflection" in result.stderr
    assert "Body finish" in result.stderr
    assert "--disable-check turning_deflection" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.parent.exists()


@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_repeatable_disable_check_includes_existing_checks_without_sheet_warnings(
    tmp_path, profile, run_turning_cli
):
    # No CAD, diagrams or machine classification: every opt-out must take effect.
    text = PLAN.replace('machine_kind = "other"\n', "")
    result, out = run_turning_cli(
        tmp_path,
        text,
        "--profile",
        profile,
        "--disable-check",
        "stock_fit",
        "--disable-check",
        "setup_diagrams",
        "--disable-check",
        "turning_deflection",
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    html = out.read_text(encoding="utf-8").lower()
    for internal in ("turning_deflection", "disabled", "warning", "certificate"):
        assert internal not in html


def turning_profile(tmp_path):
    directory = tmp_path / "profiles"
    directory.mkdir()
    config = directory / "limits.toml"
    config.write_text("[limits]\nfinish_mm = 1e-20\n", encoding="utf-8")
    profile = directory / "turning.toml"
    profile.write_text(
        'name = "Turning"\nfeatures = []\nenforce = ["turning_deflection"]\n'
        'turning_config = "limits.toml"\n',
        encoding="utf-8",
    )
    return profile, config


def test_profile_relative_partial_turning_config_and_cli_override(
    tmp_path, run_turning_cli
):
    profile, _ = turning_profile(tmp_path)
    result, out = run_turning_cli(tmp_path, TURNING_PLAN, "--profile", str(profile))
    assert result.returncode == 2
    assert "turning_deflection" in result.stderr
    assert not out.exists()
    override = tmp_path / "override.toml"
    override.write_text("[limits]\nfinish_mm = 0.005\n", encoding="utf-8")
    result, out = run_turning_cli(
        tmp_path,
        TURNING_PLAN,
        "--profile",
        str(profile),
        "--turning-config",
        str(override),
    )
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    assert "turning_deflection" not in html
    assert "Body finish" not in html
    assert "certificate" not in html.lower()


@pytest.mark.parametrize(
    "source_kind", ["profile_config", "cli_config", "default_config"]
)
@pytest.mark.parametrize("alias", ["direct", "hardlink"])
def test_output_cannot_replace_active_turning_config(
    tmp_path, source_kind, alias, monkeypatch, capsys
):
    from prechips.cli import main
    from prechips.turning import DEFAULT_CONFIG

    profile, config = turning_profile(tmp_path)
    options = ["--profile", str(profile)]
    source = config
    if source_kind == "cli_config":
        source = tmp_path / "override.toml"
        source.write_text("[limits]\nfinish_mm = 0.005\n", encoding="utf-8")
        options += ["--turning-config", str(source)]
    elif source_kind == "default_config":
        source = tmp_path / "default-turning.toml"
        source.write_bytes(DEFAULT_CONFIG.read_bytes())
        monkeypatch.setattr("prechips.cli.DEFAULT_CONFIG", source)
        monkeypatch.setattr("prechips.turning.DEFAULT_CONFIG", source)
    before = source.read_bytes()
    output = source
    if alias == "hardlink":
        output = tmp_path / "alias.html"
        output.hardlink_to(source)
    plan = tmp_path / "plan.toml"
    plan.write_text(TURNING_PLAN, encoding="utf-8")
    assert main(["traveler", str(plan), "--out", str(output), *options]) == 2
    assert "output must not overwrite" in capsys.readouterr().err
    assert source.read_bytes() == before
    assert output.read_bytes() == before


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('machine_kind = "lathe"', 'machine_kind = "mill"', "machine_kind"),
        ('cut_kind = "longitudinal_turning"', 'cut_kind = "facing"', "cut_kind"),
        ('phase = "finish"', 'phase = "polish"', "phase"),
        ('kind = "chuck_only"', 'kind = "steady"', "kind"),
    ],
)
def test_turning_schema_enums_apply_even_when_check_is_disabled(
    tmp_path, old, new, message, run_turning_cli
):
    result, out = run_turning_cli(
        tmp_path,
        TURNING_PLAN.replace(old, new),
        "--profile",
        stock_free_profile(tmp_path),
    )
    assert result.returncode == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('machine_kind = "lathe"\n', "", "machine_kind"),
        ('cut_kind = "longitudinal_turning"\n', "", "cut_kind"),
        ('turning_material = "steel_1018"\n', "", "turning_material"),
        (
            'turning_material = "steel_1018"',
            'turning_material = "unlisted"',
            "unlisted",
        ),
        (
            'turning_support = { kind = "chuck_only", chuck_z_mm = 0.0 }\n',
            "",
            "turning_support",
        ),
        ("\n[[setups.operations.turning_cuts]]", "", "turning_cuts"),
    ],
)
def test_missing_applicable_turning_data_fails_without_output(
    tmp_path, old, new, message, run_turning_cli
):
    profile, config = turning_profile(tmp_path)
    config.write_text("[limits]\nfinish_mm = 0.005\n", encoding="utf-8")
    if message == "turning_cuts":
        text = TURNING_PLAN.split(old)[0]
    else:
        text = TURNING_PLAN.replace(old, new)
    result, out = run_turning_cli(tmp_path, text, "--profile", str(profile))
    assert result.returncode == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.parent.exists()


def test_turning_failure_preserves_previous_output(tmp_path, run_turning_cli):
    profile, _ = turning_profile(tmp_path)
    out = tmp_path / "out" / "traveler.html"
    out.parent.mkdir()
    out.write_bytes(b"Previous traveler")
    result, out = run_turning_cli(tmp_path, TURNING_PLAN, "--profile", str(profile))
    assert result.returncode == 2
    assert "turning_deflection" in result.stderr
    assert out.read_bytes() == b"Previous traveler"


@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_default_turning_pass_is_silent_on_sheet(tmp_path, profile, run_turning_cli):
    result, out = run_turning_cli(
        tmp_path,
        TURNING_PLAN,
        "--profile",
        profile,
        "--disable-check",
        "stock_fit",
        "--disable-check",
        "setup_diagrams",
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    html = out.read_text(encoding="utf-8")
    assert "turning_deflection" not in html
    assert "Body finish" not in html
    assert "certificate" not in html.lower()


def test_native_numeric_binding_preserves_out_of_range_feed_precision(
    tmp_path, run_turning_cli
):
    from prechips.traveler import load_plan

    profile, config = turning_profile(tmp_path)
    config.write_text("[limits]\nfinish_mm = 0.005\n", encoding="utf-8")
    # A default text binding rounds this to the valid 0.0254 mm/rev endpoint.
    # Analysis must retain the actual below-table number and refuse it.
    feed = 0.025399999999999997
    text = TURNING_PLAN.replace(
        "[[tools]]", f"[parameters]\ncut_feed = {feed!r}\n\n[[tools]]", 1
    ).replace("feed_mm_rev = 0.05", 'feed_mm_rev = "{{process.cut_feed}}"')
    result, out = run_turning_cli(tmp_path, text, "--profile", str(profile))
    assert result.returncode == 2
    assert "outside configured feed-factor table" in result.stderr
    assert "no extrapolation" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()
    loaded = load_plan(tmp_path / "plan.toml")
    cut = loaded.data["setups"][0]["operations"][0]["turning_cuts"][0]
    assert cut["feed_mm_rev"] == feed


@pytest.mark.parametrize("machine_kind", ["lathe", "other"])
def test_explicitly_out_of_scope_operations_need_no_turning_inputs(
    tmp_path, machine_kind, run_turning_cli
):
    profile, _ = turning_profile(tmp_path)
    text = PLAN.replace('machine_kind = "other"', f'machine_kind = "{machine_kind}"')
    if machine_kind == "lathe":
        text = text.replace(
            'tool = "internal-mill-id"',
            'cut_kind = "other"\ntool = "internal-mill-id"',
        )
    result, out = run_turning_cli(tmp_path, text, "--profile", str(profile))
    assert result.returncode == 0, result.stderr
    assert "turning_deflection" not in out.read_text(encoding="utf-8")
