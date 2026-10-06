"""Plan-authored joint identity, tolerance extremes and consumer boundaries."""

import hashlib
import json
import tomllib

import pytest
from test_input_contracts import FEATURES, bundle_files
from test_stock_routes import JOINT

from prechips.inputs import BadInput, load_bundle
from prechips.rules import (
    coverage,
    finish_coverage,
    inspection,
    joints,
    sizing,
    speeds_feeds,
    tip_endpoints,
    turned_profile,
)


def _plan(socket=(10.0, 10.125), spigot=(9.875, 10.0), fit="clearance", band=(0.0, 0.25)):
    method = "press" if fit == "interference" else "silver_braze"
    return f'''part = "scratch"
features = "features.toml"
[paths]
inventory = "inventory.toml"
policy = "policy.toml"
cutting_data = "cutting.toml"
[[stock.components]]
id = "body"
[[stock.components]]
id = "boss"
[joint_features.socket]
kind = "cylinder_bore"
component = "body"
at = [0, 0, 0]
axis = [0, 0, 1]
dia = {json.dumps(socket)}
nominal_dia = {socket[0]}
depth = 5.0
thru = false
cite = "AUTHOR'S CHOICE: socket preparation"
[joint_features.spigot]
kind = "cylinder_spigot"
component = "boss"
at = [0, 0, 0]
axis = [0, 0, 1]
dia = {json.dumps(spigot)}
nominal_dia = {spigot[0]}
depth = 5.0
thru = false
cite = "AUTHOR'S CHOICE: spigot preparation"
[[setups]]
id = "B"
stock_in = "stock.body"
[[setups.ops]]
op = 10
do = "drill"
feature = "socket"
tool = "drill"
checks = {{dia = "gauge"}}
[[setups]]
id = "P"
stock_in = "stock.boss"
[[setups.ops]]
op = 10
do = "finish_turn"
feature = "spigot"
[[setups]]
id = "J"
stock_in = ["B", "P"]
[setups.joint]
kind = "cylindrical"
socket = "socket"
spigot = "spigot"
fit = "{fit}"
{fit}_mm = {json.dumps(band)}
method = "{method}"
process = "AUTHOR'S CHOICE: prepare, inspect and join coaxial components"
cite = "AUTHOR'S CHOICE: diametral fit"
[[setups.ops]]
op = 10
do = "fit"
feature = "subject"
'''


def _load(tmp_path, text=None, features=FEATURES):
    return load_bundle(bundle_files(tmp_path, _plan() if text is None else text, features))


@pytest.mark.parametrize(
    "socket, spigot, fit, band",
    [
        ((10.0, 10.125), (9.875, 10.0), "clearance", (0.0, 0.25)),
        ((9.875, 10.0), (10.125, 10.25), "interference", (0.125, 0.375)),
        ((10.0, 10.0), (10.0, 10.0), "clearance", (0.0, 0.0)),
    ],
)
def test_fit_accepts_all_extremes_exactly_on_declared_endpoints(
    tmp_path, socket, spigot, fit, band
):
    bundle = _load(tmp_path, _plan(socket, spigot, fit, band))
    (row,) = joints.evaluate_fit(bundle)
    assert row.subject == "J" and row.status == "pass"
    assert row.numbers["guaranteed_mm"] == pytest.approx(band)
    assert row.numbers["engagement_mm"] == pytest.approx(5.0)


@pytest.mark.parametrize(
    "fit, socket, spigot, band, violation",
    [
        ("clearance", (10.0, 10.125), (9.875, 10.0), (0.01, 0.25), "clearance_below_band"),
        ("clearance", (10.0, 10.125), (9.875, 10.0), (0.0, 0.24), "clearance_above_band"),
        ("clearance", (10.0, 10.125), (9.875, 10.01), (0.0, 0.25), "clearance_below_band"),
        ("interference", (9.875, 10.0), (10.125, 10.25), (0.13, 0.375), "interference_below_band"),
        ("interference", (9.875, 10.0), (10.125, 10.25), (0.125, 0.37), "interference_above_band"),
    ],
)
def test_fit_refuses_incompatible_extreme_even_when_nominal_fits(
    tmp_path, fit, socket, spigot, band, violation
):
    bundle = _load(tmp_path, _plan(socket, spigot, fit, band))
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "error"
    assert violation in row.numbers["violations"]


def test_model_unit_diameters_convert_once_but_fit_band_stays_mm(tmp_path):
    bundle = _load(
        tmp_path,
        _plan(socket=(1.0, 1.125), spigot=(0.875, 1.0), band=(0.0, 6.35)),
        FEATURES.replace('units = "mm"', 'units = "in"'),
    )
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "pass"
    assert row.numbers["guaranteed_mm"] == pytest.approx([0.0, 6.35])
    assert row.numbers["engagement_mm"] == pytest.approx(127.0)


@pytest.mark.parametrize(
    "before, after, violation",
    [
        ("axis = [0, 0, 1]", "axis = [0, 1, 0]", "axes_not_collinear"),
        ("at = [0, 0, 0]", "at = [1, 0, 0]", "axes_not_collinear"),
        ("at = [0, 0, 0]", "at = [0, 0, 5]", "no_engagement"),
    ],
)
def test_valid_cylinders_still_need_collinear_positive_engagement(
    tmp_path, before, after, violation
):
    bundle = _load(tmp_path, _plan().replace(before, after, 1))
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "error"
    assert violation in row.numbers["violations"]


@pytest.mark.parametrize(
    "before, after",
    [
        ('kind = "cylinder_bore"\n', ""),
        ('kind = "cylinder_bore"', 'kind = "unknown"'),
        ('cite = "AUTHOR\'S CHOICE: socket preparation"\n', ""),
        ('cite = "AUTHOR\'S CHOICE: socket preparation"', 'cite = []'),
        ('axis = [0, 0, 1]\n', ""),
        ('axis = [0, 0, 1]', 'axis = [0, 0, 2]'),
        ('dia = [10.0, 10.125]', 'dia = [10.125, 10.0]'),
        ('nominal_dia = 10.0\n', ""),
        ('nominal_dia = 10.0', 'nominal_dia = 11.0'),
        ('depth = 5.0', 'depth = 0.0'),
        ('depth = 5.0', 'depth = inf'),
        ('thru = false', 'thru = "unknown"'),
        ('component = "body"', 'component = "missing"'),
        ('socket = "socket"', 'socket = "missing"'),
        ('socket = "socket"', 'socket = "spigot"'),
        ('method = "silver_braze"', 'method = "press"'),
        ('kind = "cylindrical"\n', ""),
        ('cite = "AUTHOR\'S CHOICE: diametral fit"\n', ""),
        ('cite = "AUTHOR\'S CHOICE: diametral fit"', 'cite = "unknown"'),
        ('stock_in = ["B", "P"]', 'stock_in = "B"'),
        (
            'process = "AUTHOR\'S CHOICE: prepare, inspect and join coaxial components"',
            'process = "unknown"',
        ),
    ],
)
def test_malformed_joint_identity_or_known_geometry_is_bad_input(tmp_path, before, after):
    with pytest.raises(BadInput):
        _load(tmp_path, _plan().replace(before, after, 1))


def test_through_socket_still_requires_finite_positive_depth(tmp_path):
    text = _plan().replace("thru = false", "thru = true", 1).replace("depth = 5.0", "depth = -1.0", 1)
    with pytest.raises(BadInput):
        _load(tmp_path, text)


@pytest.mark.parametrize(
    "before, after",
    [
        ('nominal_dia = 10.0', 'nominal_dia = "unknown"'),
        ('dia = [10.0, 10.125]', 'dia = "unknown"'),
        ('axis = [0, 0, 1]', 'axis = "unknown"'),
        ('depth = 5.0', 'depth = "unknown"'),
        ('clearance_mm = [0.0, 0.25]', 'clearance_mm = "unknown"'),
    ],
)
def test_unknown_numeric_joint_geometry_is_debt_not_an_inferred_fit(tmp_path, before, after):
    bundle = _load(tmp_path, _plan().replace(before, after, 1))
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "unknown"


@pytest.mark.parametrize("target", ["other_branch", "joined_branch"])
def test_transient_operation_cannot_claim_another_or_already_joined_component(tmp_path, target):
    if target == "other_branch":
        text = _plan().replace('feature = "socket"', 'feature = "spigot"', 1)
    else:
        text = _plan().replace('feature = "subject"', 'feature = "socket"')
    with pytest.raises(BadInput):
        _load(tmp_path, text)


def test_joint_features_must_belong_to_distinct_consumed_branches(tmp_path):
    text = _plan().replace('component = "boss"', 'component = "body"')
    # Keep operations on their own branches so the joint itself is the refusal.
    text = text.replace('feature = "spigot"', 'feature = "subject"')
    with pytest.raises(BadInput):
        _load(tmp_path, text)


def test_transient_feature_identity_cannot_shadow_exported_geometry(tmp_path):
    features = FEATURES + '\n[features.socket]\nkind = "hole"\nrequirements = []\n'
    with pytest.raises(BadInput):
        _load(tmp_path, features=features)


@pytest.mark.parametrize("source", ['["B", "P"]', '["B"]', '["B", "P", "stock.third"]'])
def test_every_array_requires_a_joint_and_exactly_two_pieces(tmp_path, source):
    text = _plan().replace('stock_in = ["B", "P"]', f"stock_in = {source}")
    if source == '["B", "P"]':
        start = text.index("[setups.joint]")
        stop = text.index("[[setups.ops]]", start)
        text = text[:start] + text[stop:]
    elif "third" in source:
        text = text.replace(
            "[joint_features.socket]",
            '[[stock.components]]\nid = "third"\n[joint_features.socket]',
        )
    with pytest.raises(BadInput):
        _load(tmp_path, text)


@pytest.mark.parametrize(
    "before, after",
    [
        ('kind = "surface"', 'kind = "unknown"'),
        ('method = "weld"', 'method = "press"'),
        ('normal = [1, 0, 0]', 'normal = [2, 0, 0]'),
        ('x = [0, 1, 0]', 'x = [1, 0, 0]'),
        ('size_mm = [40, 20]', 'size_mm = [40, 0]'),
        ('cite = "Internal butt interface"', 'cite = ""'),
    ],
)
def test_surface_interfaces_require_known_identity_and_valid_rectangles(tmp_path, before, after):
    text = _plan()
    start, stop = text.index("[joint_features.socket]"), text.index("[[setups]]")
    text = text[:start] + text[stop:]
    text = text.replace('feature = "socket"', 'feature = "subject"').replace(
        'feature = "spigot"', 'feature = "subject"'
    )
    text = text.replace('checks = {dia = "gauge"}\n', "")
    start, stop = text.index("[setups.joint]"), text.rindex("[[setups.ops]]")
    text = text[:start] + JOINT.replace(before, after) + text[stop:]
    with pytest.raises(BadInput):
        _load(tmp_path, text)


@pytest.mark.parametrize("tool_dia, status", [(10.0, "pass"), (10.125, "pass"), (10.126, "error")])
def test_transient_socket_uses_real_finishing_size_limits_without_mutating_manifest(
    tmp_path, tool_dia, status
):
    path = bundle_files(tmp_path, _plan())
    inventory = tmp_path / "inventory.toml"
    inventory.write_text(
        f'[tools.drill]\nkind = "drill"\ndia_mm = {tool_dia}\nverify = false\n',
        encoding="utf-8",
    )
    bundle = load_bundle(path)
    row = next(row for row in sizing.evaluate(bundle) if row.subject == "socket")
    assert row.status == status
    assert row.numbers["lo_mm"] == 10.0 and row.numbers["hi_mm"] == 10.125
    raw = (tmp_path / "features.toml").read_bytes()
    assert bundle.features["features"] == tomllib.loads(raw.decode())["features"]
    assert bundle.hashes["features"] == hashlib.sha256(raw).hexdigest()
    assert "socket" not in bundle.features["features"]
    assert any("plan.joint_features.socket" in cite for cite in row.cite)


@pytest.mark.parametrize("unit, factor", [("mm", 1.0), ("in", 25.4)])
@pytest.mark.parametrize(
    "resolution_mm, verify, measured, status",
    [
        (0.125, False, True, "pass"),
        (0.126, False, True, "error"),
        (0.01, True, True, "unknown"),
        (0.01, "unknown", True, "unknown"),
        (0.01, False, False, "pass"),
    ],
)
def test_measured_gauge_resolution_preserves_capability_and_trust(
    tmp_path, unit, factor, resolution_mm, verify, measured, status
):
    path = bundle_files(tmp_path, _plan())
    measurement = (
        '{by = "Inspector", date = "2026-10-05", instrument = "Resolution standard"}'
        if measured
        else '"unknown"'
    )
    (tmp_path / "inventory.toml").write_text(
        '[gauges.gauge]\nkind = "bore_gauge"\nrange_mm = [0, 20]\nverify = false\n'
        f'resolution_{unit} = {{value = {resolution_mm / factor}, '
        f'verify = {json.dumps(verify)}, measured = {measurement}}}\n',
        encoding="utf-8",
    )
    bundle = load_bundle(path)
    row = next(row for row in inspection.evaluate(bundle) if row.subject == "socket:dia")
    assert row.status == status
    assert row.numbers["limits"] == [10.0, 10.125]
    if status != "unknown":
        assert row.numbers["resolution_mm"] == pytest.approx(resolution_mm)


@pytest.mark.parametrize("final_cut, status", [(False, "error"), (True, "pass")])
def test_transient_completion_cannot_credit_final_faces_even_with_explicit_override(
    tmp_path, final_cut, status
):
    features = FEATURES.replace(
        "requirements = []",
        'requirements = ["finish_ra"]\nfinish_ra = 1.6\nfaces = ["#1"]',
    )
    text = _plan().replace('id = "J"', 'id = "J"\nmachine = "mill"')
    bundle = _load(tmp_path, text, features)
    bundle.plan["stock"]["as_is_faces"] = []
    # These deliberately adversarial raw facts claim the final face as well as
    # completed preparation. Host coverage must still reject transient credit.
    for setup in bundle.plan["setups"][:2]:
        setup["ops"][0]["faces"] = ["#1"]
    if final_cut:
        bundle.plan["setups"][2]["ops"].append(
            {"op": 20, "do": "finish_profile", "feature": "subject"}
        )
    object.__setattr__(
        bundle,
        "kernel",
        {
            "status": "ok",
            "faces": [{"ref": "#1", "index": 0}],
            "mapping": {"#1": 0},
            "mapping_errors": {},
            "features": {"subject": [0], "socket": [1], "spigot": [2]},
            "setups": {
                "B": {"completed_joint_features": ["socket"]},
                "P": {"completed_joint_features": ["spigot"]},
            },
            "ops": {
                subject: {
                    "claimed_indices": [0],
                    "claim_errors": [],
                }
                for subject in ("B:10", "P:10", "J:20")
            },
        },
    )
    (covered,) = coverage.evaluate(bundle)
    (finished,) = finish_coverage.evaluate(bundle)
    assert covered.status == finished.status == status
    assert covered.numbers["unclaimed_indices"] == ([] if final_cut else [0])
    assert finished.subject == "subject"
    assert finished.numbers["uncovered_faces"] == ([] if final_cut else [0])


def test_exported_faces_cannot_refer_to_transient_labels(tmp_path):
    features = FEATURES + '\nfaces = ["plan.joint_features.socket"]\n'
    with pytest.raises(BadInput):
        _load(tmp_path, features=features)


@pytest.mark.parametrize("units, status", [("in", "pass"), ("mm", "error"), ("unknown", "unknown")])
def test_blind_joint_depth_converts_model_units_but_operation_depth_stays_mm(
    tmp_path, units, status
):
    text = _plan().replace("depth = 5.0", "depth = 1.0", 1)
    bundle = _load(tmp_path, text, FEATURES.replace('units = "mm"', f'units = "{units}"'))
    bundle.plan["setups"][0]["stock_state"] = {"top_z": 0.0}
    bundle.plan["setups"][0]["ops"][0]["depth_mm"] = 20.0
    bundle.inventory["tools"] = {
        "drill": {"kind": "drill", "dia_mm": 1.0, "point_angle": 118.0, "verify": False}
    }
    row = next(row for row in tip_endpoints.evaluate(bundle) if row.subject == "socket")
    assert row.status == status
    endpoint = row.numbers["endpoints"][0]
    assert endpoint["depth_mm"] == 20.0
    assert endpoint["depth_limit_mm"] == {"in": 25.4, "mm": 1.0, "unknown": "unknown"}[units]


def test_inch_spigot_nominal_drives_lathe_rpm_in_physical_units(tmp_path):
    bundle = _load(
        tmp_path,
        _plan(socket=(1.1, 1.2), spigot=(1.0, 1.05), band=(0.0, 6.0)),
        FEATURES.replace('units = "mm"', 'units = "in"'),
    )
    setup = bundle.plan["setups"][1]
    setup["machine"] = "lathe"
    setup["ops"][0]["tool"] = "turn"
    bundle.plan["stock"]["material"] = "1018"
    bundle.inventory["machines"]["lathe"] = {
        "kind": "lathe", "spindle": {"ranges_rpm": [[70, 2200]]}, "verify": False
    }
    bundle.inventory["tools"] = {
        "turn": {"kind": "turning", "material": "HSS", "verify": False}
    }
    bundle.cutting_data.update(
        aliases={"1018": "low_carbon_steel"},
        cut=[{
            "material_class": "low_carbon_steel",
            "tool_material": "HSS",
            "operation": "finish_turn",
            "diameter_range": [25.0, 26.0],
            "sfm": 100.0,
            "feed_mm_rev": 0.1,
            "cite": "Test cutting table: one-inch steel turning",
        }],
    )
    row = next(row for row in speeds_feeds.evaluate(bundle) if row.subject == "P:10")
    assert row.status == "pass"
    assert row.numbers["diameter_in"] == pytest.approx(1.0)
    assert row.numbers["rpm"] == 400
    assert row.numbers["feed_mm_min"] == pytest.approx(40.0)


def test_transient_profile_exists_only_on_prepared_component_lineage(tmp_path):
    bundle = _load(tmp_path)
    preparation = bundle.plan["setups"][1]
    uncut = {
        "id": "P0", "stock_in": "stock.boss",
        "ops": [{"op": 10, "do": "inspect", "feature": "subject"}],
    }
    bundle.plan["setups"].insert(0, uncut)
    preparation["stock_in"] = "P0"
    after = {
        "id": "P1", "stock_in": "P",
        "ops": [{"op": 10, "do": "inspect", "feature": "subject"}],
    }
    bundle.plan["setups"].insert(3, after)
    for setup in bundle.plan["setups"]:
        profile = turned_profile.exposed_profile(bundle, setup)
        assert ("spigot" in profile["names"]) == (setup["id"] in {"P", "P1"})


@pytest.mark.parametrize(
    "sign, at, axis, expected",
    [
        (1, [1, 2, 3], [1, 0, 0], [0.0, 5.0]),
        (-1, [1, 2, 3], [1, 0, 0], [-5.0, 0.0]),
        (1, [1, 2.1, 3], [1, 0, 0], None),
        (1, [1, 2, 3], [0.7071067811865476, 0.7071067811865476, 0], None),
    ],
)
def test_rotated_transient_profile_uses_actual_axis_and_spindle_line(
    tmp_path, sign, at, axis, expected
):
    features = FEATURES.replace('frames = "unknown"\n', "") + f'''
[frames.turn]
origin = [1, 2, 3]
x = [0, 1, 0]
y = [0, 0, {sign}]
z = [{sign}, 0, 0]
binding = "nominal"
'''
    text = (
        _plan()
        .replace("at = [0, 0, 0]", f"at = {json.dumps(at)}")
        .replace("axis = [0, 0, 1]", f"axis = {json.dumps(axis)}")
        .replace('id = "P"', 'id = "P"\nframe = "turn"')
    )
    bundle = _load(tmp_path, text, features)
    profile = turned_profile.exposed_profile(bundle, bundle.plan["setups"][1])
    if expected is None:
        assert "spigot" in profile["unresolved"]
        assert not any(row["feature"] == "spigot" for row in profile["intervals"])
    else:
        interval = next(row for row in profile["intervals"] if row["feature"] == "spigot")
        assert interval["z_mm"] == pytest.approx(expected)
        assert interval["diameter_mm"] == pytest.approx(9.875)
        assert "spigot" not in profile["unresolved"]


def test_nested_two_reference_assembly_cannot_hide_a_third_supply_component(tmp_path):
    text = _plan()
    start, stop = text.index("[joint_features.socket]"), text.index("[[setups]]")
    text = (
        text[:start] + '[[stock.components]]\nid = "third"\n' + text[stop:]
    )
    text = text.replace('feature = "socket"', 'feature = "subject"').replace(
        'feature = "spigot"', 'feature = "subject"'
    )
    text = text.replace('checks = {dia = "gauge"}\n', "")
    start, stop = text.index("[setups.joint]"), text.rindex("[[setups.ops]]")
    text = text[:start] + JOINT + text[stop:]
    text += (
        '\n[[setups]]\nid = "J2"\nstock_in = ["J", "stock.third"]\n'
        + JOINT
        + '[[setups.ops]]\nop = 10\ndo = "fit"\nfeature = "subject"\n'
    )
    with pytest.raises(BadInput):
        _load(tmp_path, text)
