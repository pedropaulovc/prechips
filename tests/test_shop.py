import pytest

from prechips.cli import main
from prechips.traveler import load_plan, render_traveler

PLAN = """\
shop = "shop.toml"
material_key = "1018"
title = "Test part"
part = "T1"
revision = "A"
material = "Printed material is not an identity"
stock = "Authored blank"

[[tools]]
id = "blade"
ref = "shaft-blade"

[[setups]]
title = "Relief"
machine = "Manual lathe"

[[setups.operations]]
tool = "blade"
settings = "relief-1018"
instruction = "Cut the relief."
"""

SHOP = """\
[tools.shaft-blade]
name = "Blade"
description = "Authored parting blade"

[settings.relief-1018]
tool = "shaft-blade"
material = "1018"
rpm = 1200
feed = "0.02 mm/rev"
"""


def prepare(tmp_path, plan_text=PLAN, shop_text=SHOP):
    plan = tmp_path / "plan.toml"
    plan.write_text(plan_text, encoding="utf-8")
    shop = tmp_path / "shop.toml"
    shop.write_text(shop_text, encoding="utf-8")
    profile = tmp_path / "rendering.toml"
    profile.write_text('name = "Rendering only"\nfeatures = []\nenforce = []\n')
    return plan, shop, profile


def operation(loaded):
    return loaded.data["setups"][0]["operations"][0]


def test_two_consumers_follow_shared_file_edits(tmp_path):
    plan, shop, _ = prepare(tmp_path)
    other = tmp_path / "second.toml"
    other.write_text(PLAN.replace('part = "T1"', 'part = "T2"'), encoding="utf-8")
    for path in (plan, other):
        loaded = load_plan(path)
        assert loaded.shop == shop.resolve()
        assert loaded.cad is None
        assert loaded.data["tools"][0]["description"] == "Authored parting blade"
        assert operation(loaded)["rpm"] == 1200
        assert operation(loaded)["feed"] == "0.02 mm/rev"
    shop.write_text(
        SHOP.replace("Authored parting blade", "Replacement blade")
        .replace("1200", "950")
        .replace("0.02 mm/rev", "Hand plunge"),
        encoding="utf-8",
    )
    for path in (plan, other):
        loaded = load_plan(path)
        assert loaded.data["tools"][0]["description"] == "Replacement blade"
        assert operation(loaded)["rpm"] == 950
        assert operation(loaded)["feed"] == "Hand plunge"
        assert "Replacement blade" in render_traveler(loaded)
        assert "shop" not in loaded.data
        assert "material_key" not in loaded.data
        assert "ref" not in loaded.data["tools"][0]
        assert "settings" not in operation(loaded)


@pytest.mark.parametrize(
    ("tool_override", "operation_override", "name", "description", "rpm", "feed"),
    [
        (
            'name = "Local blade"',
            "rpm = 800",
            "Local blade",
            "Authored parting blade",
            800,
            "0.02 mm/rev",
        ),
        (
            'description = "Local description"',
            'feed = "Hand"',
            "Blade",
            "Local description",
            1200,
            "Hand",
        ),
    ],
)
def test_field_overrides_are_independent(
    tmp_path, tool_override, operation_override, name, description, rpm, feed
):
    text = PLAN.replace('ref = "shaft-blade"', f'ref = "shaft-blade"\n{tool_override}')
    text += f"\n{operation_override}\n"
    plan, _, _ = prepare(tmp_path, text)
    loaded = load_plan(plan)
    assert loaded.data["tools"][0]["name"] == name
    assert loaded.data["tools"][0]["description"] == description
    assert operation(loaded)["rpm"] == rpm
    assert operation(loaded)["feed"] == feed


def test_bind_only_plan_owned_strings(tmp_path):
    text = (
        PLAN.replace(
            'ref = "shaft-blade"',
            'ref = "shaft-blade"\nname = "Blade for {{process.quantity}} blanks"',
        )
        + "\n[parameters]\nquantity = 2\n"
    )
    shared = SHOP.replace("Authored parting blade", "{{cad.not_a_feature}}")
    shared = shared.replace("0.02 mm/rev", "{{process.quantity}} literal feed")
    plan, _, _ = prepare(tmp_path, text, shared)
    loaded = load_plan(plan)
    assert loaded.data["tools"][0]["name"] == "Blade for 2 blanks"
    assert loaded.data["tools"][0]["description"] == "{{cad.not_a_feature}}"
    assert operation(loaded)["feed"] == "{{process.quantity}} literal feed"
    assert "{{cad.not_a_feature}}" in render_traveler(loaded)


@pytest.mark.parametrize(
    ("plan_text", "shop_text", "message"),
    [
        (PLAN.replace('shop = "shop.toml"\n', ""), SHOP, "requires plan.shop"),
        (PLAN.replace("shop.toml", "missing.toml"), SHOP, "missing.toml"),
        (
            PLAN.replace('ref = "shaft-blade"', 'ref = "missing"'),
            SHOP,
            "unknown shared tools reference",
        ),
        (
            PLAN.replace('settings = "relief-1018"', 'settings = "missing"'),
            SHOP,
            "unknown shared settings reference",
        ),
        (PLAN.replace('material_key = "1018"\n', ""), SHOP, "requires material_key"),
        (
            PLAN.replace('material_key = "1018"', 'material_key = "steel"'),
            SHOP,
            "requires material_key",
        ),
        (PLAN.replace('tool = "blade"\n', ""), SHOP, "requires tool ref"),
        (
            PLAN.replace('ref = "shaft-blade"', 'description = "Inline blade"'),
            SHOP,
            "requires tool ref",
        ),
        (
            PLAN,
            SHOP.replace('tool = "shaft-blade"', 'tool = "other"'),
            "requires tool ref",
        ),
        (PLAN, SHOP.replace("rpm = 1200", "rpm = true"), "positive integer"),
        (PLAN, SHOP.replace("rpm = 1200", "rpm = 0"), "positive integer"),
        (PLAN, SHOP.replace("rpm = 1200", "rpm = 1.5"), "positive integer"),
        (
            PLAN,
            SHOP.replace('feed = "0.02 mm/rev"', 'feed = " "'),
            "nonempty string",
        ),
        (
            PLAN,
            SHOP.replace('rpm = 1200\nfeed = "0.02 mm/rev"\n', ""),
            "expected rpm or feed",
        ),
        (
            PLAN,
            SHOP.replace('material = "1018"', 'material = ""'),
            "nonempty string",
        ),
        (
            PLAN,
            SHOP.replace('description = "Authored parting blade"', "description = 1"),
            "nonempty string",
        ),
        (PLAN, SHOP + "unknown = 1\n", "unknown field"),
        (
            PLAN,
            SHOP.replace("[tools.shaft-blade]", "[tools.shaft-blade]\nunknown = 1"),
            "unknown field",
        ),
        (PLAN, "tools = 1\n", "expected a table"),
        (PLAN, "tools = {shaft-blade = 1}\n", "expected a table"),
        (PLAN, "[broken", "Expected"),
        (
            PLAN + '\nrpm = 800\nfeed = "Local"\n',
            SHOP.replace('tool = "shaft-blade"', 'tool = "other"'),
            "requires tool ref",
        ),
        (
            PLAN + '\nrpm = 800\nfeed = "Local"\n',
            SHOP.replace("rpm = 1200", "rpm = -1"),
            "positive integer",
        ),
    ],
)
def test_selected_input_errors_leave_output_untouched(
    tmp_path, capsys, plan_text, shop_text, message
):
    plan, _, profile = prepare(tmp_path, plan_text, shop_text)
    out = tmp_path / "traveler.html"
    out.write_text("Previous output", encoding="utf-8")
    assert (
        main(["traveler", str(plan), "--out", str(out), "--profile", str(profile)]) == 2
    )
    assert message in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "Previous output"


def test_unreferenced_records_are_not_validated(tmp_path):
    plan, _, _ = prepare(
        tmp_path,
        shop_text=SHOP
        + "\n[tools.unused]\nunknown = 1\n[settings.unused]\nrpm = false\n",
    )
    assert operation(load_plan(plan))["rpm"] == 1200


def test_inline_only_plan_needs_no_shop_or_identity(tmp_path):
    text = PLAN.replace('shop = "shop.toml"\nmaterial_key = "1018"\n', "")
    text = text.replace('ref = "shaft-blade"', 'description = "Inline blade"')
    text = text.replace('settings = "relief-1018"', 'rpm = 700\nfeed = "Hand"')
    plan, shop, _ = prepare(tmp_path, text)
    shop.unlink()
    loaded = load_plan(plan)
    assert loaded.shop is None
    assert operation(loaded)["rpm"] == 700
    assert operation(loaded)["feed"] == "Hand"


def test_tool_only_reference_needs_no_material_identity(tmp_path):
    text = PLAN.replace('material_key = "1018"\n', "")
    text = text.replace('settings = "relief-1018"\n', "")
    plan, _, _ = prepare(tmp_path, text)
    loaded = load_plan(plan)
    assert loaded.data["tools"][0]["description"] == "Authored parting blade"
    assert "rpm" not in operation(loaded)
    assert "feed" not in operation(loaded)


@pytest.mark.parametrize("omitted", ["rpm = 1200\n", 'feed = "0.02 mm/rev"\n'])
def test_setting_can_supply_only_one_field(tmp_path, omitted):
    plan, _, _ = prepare(tmp_path, shop_text=SHOP.replace(omitted, ""))
    resolved = operation(load_plan(plan))
    if omitted.startswith("rpm"):
        assert "rpm" not in resolved
        assert resolved["feed"] == "0.02 mm/rev"
    else:
        assert resolved["rpm"] == 1200
        assert "feed" not in resolved


@pytest.mark.parametrize("alias", ["direct", "hardlink", "symlink"])
def test_cli_protects_shared_input_aliases(tmp_path, capsys, alias):
    plan, shop, profile = prepare(tmp_path)
    out = shop
    if alias != "direct":
        out = tmp_path / "alias.html"
        if alias == "hardlink":
            out.hardlink_to(shop)
        else:
            try:
                out.symlink_to(shop)
            except OSError as error:
                pytest.skip(f"Symlinks unavailable: {error}")
    before = shop.read_bytes()
    assert (
        main(["traveler", str(plan), "--out", str(out), "--profile", str(profile)]) == 2
    )
    assert "output must not overwrite" in capsys.readouterr().err
    assert shop.read_bytes() == before
    assert out.read_bytes() == before
