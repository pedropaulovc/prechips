"""Phase 1 of the typed area hold (docs/design/area-hold.md): schema, trust, migration."""

import pytest
from pydantic import ValidationError

from prechips.inputs import BadInput, load_bundle
from prechips.measurements import cited_fact, limits_fact
from prechips.model import Inventory
from prechips.rules.resolution import coating_process

MEASURED = {"status": "measured", "by": "test", "date": "2026-10-11", "instrument": "mic"}
TAPE = """
[consumables.tape]
kind = "adhesive_tape"
name = "film tape"
products = ["film tape, 50 mm roll"]
width_mm = 50.0
shear_n_per_cm2 = { value = 3.0, test = "shear", pairs = [{ work = "steel", seat = "al" }] }
peel_n_per_cm = { value = 4.0, test = "180 deg peel", cite = "test datasheet" }
dwell_min = { value = 20, cite = "test datasheet" }
surface_prep = "Clean both faces."
apply = "Roll firmly."
release = { method = "solvent", agent = "isopropyl alcohol", wait_min = 5, cite = "test" }
[consumables.tape.thickness_mm]
value = [0.090, 0.110]
measured = { status = "measured", by = "test", date = "2026-10-11", instrument = "mic" }
"""
PLATE = """
[fixtures.subplate]
kind = "custom"
[[fixtures.subplate.solids]]
name = "plate"
supply = "bought"
shape = "box"
material = "MIC-6"
at_mm = [-50.0, -50.0, -10.0]
size_mm = [100.0, 100.0, 10.0]
[[fixtures.subplate.solids]]
name = "hole"
shape = "cylinder"
at_mm = [0.0, 0.0, -10.0]
axis = [0.0, 0.0, 1.0]
dia_mm = 6.0
length_mm = 10.0
void = true
"""
PLAN = """part = "scratch"
features = "features.toml"
[paths]
inventory = "inventory.toml"
policy = "policy.toml"
cutting_data = "cutting.toml"
[[setups]]
id = "S1"
machine = "mill"
[setups.hold]
{hold}
[[setups.ops]]
op = 10
do = "inspect"
feature = "subject"
"""
FEATURES = """part = "scratch"
units = "mm"
frames = "unknown"
[features.subject]
kind = "face"
requirements = []
"""


def bundle(tmp_path, hold, inventory=TAPE + PLATE, plan=PLAN):
    files = {
        "plan.toml": plan.replace("{hold}", hold),
        "features.toml": FEATURES,
        "inventory.toml": '[machines.mill]\nkind = "mill"\n' + inventory,
        "policy.toml": "",
        "cutting.toml": "revision = 1\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return load_bundle(tmp_path / "plan.toml")


def tape(**fields):
    base = {"kind": "adhesive_tape"}
    return Inventory.model_validate({"consumables": {"t": {**base, **fields}}})


# --- schema ---------------------------------------------------------------------------


def test_typed_tape_records_load_beside_plain_consumables(tmp_path):
    loaded = bundle(tmp_path, 'fixture = "subplate"\narea = { ref = "tape", on = "plate" }')
    inventory = loaded.inventory
    assert inventory["consumables"]["tape"]["kind"] == "adhesive_tape"
    assert inventory["consumables"]["tape"]["width_mm"] == 50.0
    assert inventory["fixtures"]["subplate"]["solids"][0]["material"] == "MIC-6"
    assert loaded.plan["setups"][0]["hold"]["area"] == {"ref": "tape", "on": "plate"}
    plain = Inventory.model_validate({"consumables": {"oil": {"name": "oil", "products": ["a"]}}})
    assert plain.model_dump(exclude_unset=True)["consumables"]["oil"]["products"] == ["a"]


@pytest.mark.parametrize(
    "fields,match",
    [
        ({"static_shear_n_per_cm2": {"value": 3.0}}, "Extra inputs"),
        ({"kind": "wax"}, "adhesive_tape"),
        ({"shear_n_per_cm2": {"value": -1.0, "cite": "x"}}, "must be > 0"),
        ({"dwell_min": {"value": 0, "cite": "x"}}, "must be > 0"),
        ({"width_mm": 0.0}, "width_mm must be > 0"),
        ({"width_mm": {"value": -5.0, "measured": MEASURED}}, "width_mm must be > 0"),
        ({"thickness_mm": {"value": [0.11, 0.09], "measured": MEASURED}}, "ordered"),
        ({"thickness_mm": [0.0, 0.1]}, "ordered"),
        ({"release": {"method": "solvent", "temp_c": 70.0}}, "agent, not a temp_c"),
        ({"release": {"method": "heat", "agent": "alcohol"}}, "temp_c, not an agent"),
        ({"release": {"method": "heat", "wait_min": 0.0}}, "must be > 0"),
        ({"release": {"method": "scrape"}}, "solvent"),
        ({"shear_n_per_cm2": {"value": 3.0, "pairs": []}}, "at least 1"),
        ({"peel_n_per_cm": {"value": 3.0, "pairs": [{"work": "steel"}]}}, "work and seat"),
        (
            {"peel_n_per_cm": {"value": 3.0, "pairs": [{"work": " ", "seat": "al"}]}},
            "work and seat",
        ),
        ({"peel_n_per_cm": {"value": 3.0, "pairs": [{"work": "a", "face": "b"}]}}, "Extra inputs"),
    ],
)
def test_malformed_tape_records_are_bad_input(fields, match):
    with pytest.raises(ValidationError, match=match):
        tape(**fields)


def test_seat_solid_states_its_flatness_and_contact_material():
    flat = {"value": 0.005, "measured": MEASURED}
    solid = {"name": "plate", "shape": "box", "flatness_mm": flat, "material": "MIC-6"}
    loaded = Inventory.model_validate(
        {"fixtures": {"p": {"kind": "custom", "solids": [solid]}}}
    ).model_dump(exclude_unset=True)
    assert loaded["fixtures"]["p"]["solids"][0] == solid


@pytest.mark.parametrize(
    "item",
    [
        {"kind": "vacuum", "vacuum_kpa": {"value": 80.0}},  # deferred to #309: no typed facts
        {"kind": "vacuum_gauge", "range_kpa": [0.0, 100.0]},
        {"kind": "micrometer", "accuracy_mm": 0.002},  # recipe B is out of scope
    ],
)
def test_deferred_vacuum_and_recipe_b_facts_are_not_schema(item):
    with pytest.raises(ValidationError, match="Extra inputs"):
        Inventory.model_validate({"gauges" if "gauge" in item["kind"] else "fixtures": {"x": item}})


def test_strengths_keep_their_exact_pairs(tmp_path):
    loaded = bundle(tmp_path, 'fixture = "subplate"\narea = { ref = "tape", on = "plate" }')
    shear = loaded.inventory["consumables"]["tape"]["shear_n_per_cm2"]
    assert shear["pairs"] == [{"work": "steel", "seat": "al"}]


def test_z_touch_point_is_a_setup_frame_pair(tmp_path):
    plan = PLAN.replace(
        "[[setups.ops]]",
        '[setups.zero.z]\nmethod = "touch"\nat_mm = [-190.0, 20.0]\n[[setups.ops]]',
    )
    loaded = bundle(tmp_path, 'fixture = "subplate"', plan=plan)
    assert loaded.plan["setups"][0]["zero"]["z"]["at_mm"] == [-190.0, 20.0]
    with pytest.raises(BadInput, match="at_mm"):
        bundle(tmp_path, 'fixture = "subplate"', plan=plan.replace("[-190.0, 20.0]", "[1.0]"))


# --- fact-local trust -----------------------------------------------------------------


@pytest.mark.parametrize(
    "fact,tested,verified,reason",
    [
        ({"value": 3.0, "cite": "datasheet"}, False, True, "own citation"),
        ({"value": 3.0, "measured": MEASURED}, False, True, "own complete shop measurement"),
        (3.0, False, False, "bare value"),
        ("unknown", False, False, "No positive"),
        ({"value": "unknown", "cite": "datasheet"}, False, False, "No positive"),
        ({"value": 3.0}, False, False, "no citation or measurement"),
        ({"value": 3.0, "cite": " "}, False, False, "no citation or measurement"),
        ({"value": 3.0, "cite": "unknown"}, False, False, "no citation or measurement"),
        ({"value": 3.0, "cite": "x", "verify": True}, False, False, "requires verification"),
        ({"value": 3.0, "cite": "x", "verify": "unknown"}, False, False, "verification"),
        (
            {"value": 3.0, "cite": "x", "measured": {**MEASURED, "status": "assumed"}},
            False,
            False,
            "assumed",
        ),
        (
            {"value": 3.0, "measured": {**MEASURED, "status": "illustrative"}},
            False,
            False,
            "illustrative",
        ),
        ({"value": 3.0, "measured": {k: MEASURED[k] for k in ("by", "date", "instrument")}},)
        + (False, False, "assumed"),
        ({"value": 3.0, "cite": "x"}, True, False, "test method"),
        ({"value": 3.0, "cite": "x", "test": " "}, True, False, "test method"),
        ({"value": 3.0, "cite": "x", "test": "unknown"}, True, False, "test method"),
        ({"value": 3.0, "cite": "x", "test": "overlap shear"}, True, True, "own citation"),
        ({"value": 3.0, "cite": "x", "measured": "unknown"}, False, False, "stated unknown"),
    ],
)
def test_cited_fact_is_trusted_only_by_its_own_qualifiers(fact, tested, verified, reason):
    result = cited_fact({"f": fact}, "f", tested=tested)
    assert result["verified"] is verified
    assert reason in result["reason"]
    if not verified:
        assert result["value"] in ("unknown", 3.0)


def test_cited_fact_never_reads_its_item_or_another_fact():
    item = {"cite": "item datasheet", "verify": False, "g": {"value": 2.0, "cite": "x"}, "f": 3.0}
    assert cited_fact(item, "f")["verified"] is False


@pytest.mark.parametrize(
    "thickness,verified",
    [
        ({"value": [0.090, 0.110], "measured": MEASURED}, True),
        ({"value": [0.090, 0.110], "measured": {**MEASURED, "status": "assumed"}}, False),
        ([0.090, 0.110], False),  # a datasheet pair is printed, never a stack proof (D4)
        ({"value": [0.090, 0.110], "measured": MEASURED, "verify": True}, False),
    ],
)
def test_tape_thickness_clears_the_stack_only_as_a_measured_pair(thickness, verified):
    fact = limits_fact({"thickness_mm": thickness}, "thickness", require_measured=True)
    assert fact["verified"] is verified
    assert fact["value"] == [0.090, 0.110]


# --- hold reference and migration ------------------------------------------------------


@pytest.mark.parametrize("method", ["tape", "Tape", " tape "])
def test_tape_method_is_bad_input_naming_the_area_form(tmp_path, method):
    with pytest.raises(BadInput, match=r"no longer a holding method: .*hold\.area = \{ ref"):
        bundle(tmp_path, f'fixture = "subplate"\nmethod = "{method}"')


def test_other_methods_and_unknown_area_identities_still_load(tmp_path):
    bundle(tmp_path, 'fixture = "subplate"\nmethod = "wax"')
    bundle(tmp_path, 'fixture = "subplate"\narea = { ref = "unknown", on = "unknown" }')
    # A vacuum hold stays untyped text until #309 designs it.
    bundle(tmp_path, 'fixture = "subplate"\nmethod = "vacuum"')


@pytest.mark.parametrize(
    "hold,match",
    [
        ('fixture = "subplate"\narea = { ref = "glue", on = "plate" }', "not a consumables"),
        ('fixture = "subplate"\narea = { ref = "subplate", on = "plate" }', "not a consumables"),
        ('fixture = "subplate"\narea = { ref = "tape", on = "top" }', r"found 0"),
        ('fixture = "subplate"\narea = { ref = "tape", on = "hole" }', r"found 0"),
    ],
)
def test_area_reference_must_resolve_to_its_kind_and_one_drawn_solid(tmp_path, hold, match):
    with pytest.raises(BadInput, match=match):
        bundle(tmp_path, hold)


@pytest.mark.parametrize(
    "fixture,error",
    [
        ('[fixtures.subplate]\nkind = "custom"\n', "found 0"),  # draws no solids: no seat
        ('[fixtures.subplate]\nkind = "custom"\nsolids = "unknown"\n', None),  # debt
        ("", None),  # an unresolved fixture is tool_resolves' finding, not a seat error
    ],
)
def test_known_seat_needs_a_drawn_solid_of_a_resolved_fixture(tmp_path, fixture, error):
    hold = 'fixture = "subplate"\narea = { ref = "tape", on = "plate" }'
    if error is None:
        bundle(tmp_path, hold, TAPE + fixture)
        return
    with pytest.raises(BadInput, match=error):
        bundle(tmp_path, hold, TAPE + fixture)


@pytest.mark.parametrize("fixture", ["subplate", "fixtures.subplate"])
def test_a_qualified_fixture_resolves_like_a_bare_one(tmp_path, fixture):
    loaded = bundle(tmp_path, f'fixture = "{fixture}"\narea = {{ ref = "tape", on = "plate" }}')
    assert loaded.plan["setups"][0]["hold"]["fixture"] == fixture
    with pytest.raises(BadInput, match="found 0"):
        bundle(tmp_path, f'fixture = "{fixture}"\narea = {{ ref = "tape", on = "hole" }}')


def test_two_solids_of_the_named_seat_are_ambiguous(tmp_path):
    twice = PLATE + (
        '[[fixtures.subplate.solids]]\nname = "plate"\nshape = "box"\n'
        "at_mm = [0.0, 0.0, 0.0]\nsize_mm = [1.0, 1.0, 1.0]\n"
    )
    with pytest.raises(BadInput, match="found 2"):
        bundle(
            tmp_path,
            'fixture = "subplate"\narea = { ref = "tape", on = "plate" }',
            TAPE + twice,
        )


def test_tape_is_not_a_coating_process():
    inventory = tape(name="film tape", products=["roll"]).model_dump(exclude_unset=True)
    assert coating_process(inventory, "t") == (None, None)
