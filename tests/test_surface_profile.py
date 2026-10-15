"""Surface-profile zones give the BASIC dimensions they govern a band (HA#1544).

An ASME Y14.5 SURFACE PROFILE ``t`` (``U`` of it on the material-added side) to a datum
reference frame holds every point of the surface inside the zone about its BASIC true
profile. A BASIC length read along the surface normal therefore reads inside a pointwise
band, and a BASIC angle of a planar face tilts at most ``asin(t / l_min)``. Anything the
zone cannot locate stays unknown, never a pass.
"""

import math

import pytest
from test_cli import run_cli
from test_manual_arc import TEMPLATE_FILING, manual_row, scratch

from prechips.inputs import BadInput, load_bundle
from prechips.rules import datum_consistency, inspection

METHOD = '"Probe the edge on the CMM in datum frame A|B|C"'
TOP_EDGE = (
    'kind = "profile"\n'
    'requirements = ["height_above_pivot", "radius", "surface_profile"]\n'
    "radius = 800.0\nheight_above_pivot = 8.0\n"
    "surface_profile = 0.5\nsurface_profile_u = 0.5\n"
    'surface_profile_datums = ["A", "B", "C"]\n'
    'surface_profile_governs = { radius = "decreases", height_above_pivot = "increases" }\n'
)
PROFILE_OUTER = (
    'kind = "profile"\n'
    'requirements = ["bottom_radius", "mirror_symmetric", "surface_profile"]\n'
    "bottom_radius = 816.0\nmirror_symmetric = true\n"
    "surface_profile = 0.5\nsurface_profile_u = 0.0\n"
    'surface_profile_datums = ["A", "B", "C"]\n'
    'surface_profile_governs = { bottom_radius = "increases" }\n'
)
# The tip land: a planar face 5.08-6.10 wide at a BASIC 10.46° and a BASIC X station read
# 10.46° off the land normal.
TIP_LAND = (
    'kind = "face"\n'
    'requirements = ["land_angle_deg", "station", "tip_land"]\n'
    "land_angle_deg = 10.46\nstation = 30.0\ntip_land = [5.08, 6.1]\n"
)


def profile(governs, *, zone="0.5", u="0.5", datums='["A", "B", "C"]', requirements="[]"):
    """A feature carrying only a profile zone that governs other features' requirements."""
    text = f'kind = "profile"\nrequirements = {requirements}\nsurface_profile = {zone}\n'
    if u is not None:
        text += f"surface_profile_u = {u}\n"
    if datums is not None:
        text += f"surface_profile_datums = {datums}\n"
    return text + f"surface_profile_governs = {governs}\n"


def write_bundle(
    tmp_path,
    features,
    *,
    subject="top_edge",
    requirement="radius",
    gauge="profile_gauge",
    method=METHOD,
    budget="0.10",
    holds="",
):
    """A two-setup mill bundle: S1 finishes the datum features base (A), axis (B) and side
    (C); S2 finishes every other manifest feature, ``subject`` checked for ``requirement``."""
    datums = {
        "base": 'kind = "face"\nrequirements = []\n',
        "axis": 'kind = "hole"\nrequirements = []\n',
        "side": 'kind = "face"\nrequirements = []\n',
    }
    manifest = (
        'part = "profile-control"\nunits = "mm"\nframes = "unknown"\n'
        '[datums.A]\nfeature = "base"\n[datums.B]\nfeature = "axis"\n'
        '[datums.C]\nfeature = "side"\n'
        + "".join(f"[features.{name}]\n{text}" for name, text in {**datums, **features}.items())
    )
    finishing = "".join(
        f'[[setups.ops]]\nop = {40 + 10 * index}\ndo = "profile"\nfeature = "{name}"\n'
        + (
            f'checks = {{ {requirement} = "gauge" }}\n'
            + (f"inspection_methods = {{ {requirement} = {method} }}\n" if method else "")
            + holds
            if name == subject
            else ""
        )
        for index, name in enumerate(features)
    )
    documents = {
        "plan.toml": (
            'part = "profile-control"\nfeatures = "features.toml"\n'
            '[paths]\ninventory = "inventory.toml"\npolicy = "policy.toml"\n'
            'cutting_data = "cutting.toml"\n'
            '[[setups]]\nid = "S1"\nmachine = "mill"\n'
            '[[setups.ops]]\nop = 10\ndo = "face"\nfeature = "base"\n'
            '[[setups.ops]]\nop = 20\ndo = "bore"\nfeature = "axis"\n'
            '[[setups.ops]]\nop = 30\ndo = "face"\nfeature = "side"\n'
            '[[setups]]\nid = "S2"\nmachine = "mill"\n' + finishing
        ),
        "features.toml": manifest,
        "inventory.toml": (
            '[machines.mill]\nkind = "mill"\n[gauges.gauge]\n'
            f'kind = "{gauge}"\nrange_mm = [0.0, 1000.0]\nresolution_mm = 0.01\n'
            "verify = false\n"
        ),
        "policy.toml": f"[numbers]\nrefixture_budget_mm = {budget}\n",
        "cutting.toml": "revision = 1\n",
    }
    for name, text in documents.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path / "plan.toml"


def bundle(tmp_path, features, **options):
    return load_bundle(write_bundle(tmp_path, features, **options))


def band(tmp_path, features, name, requirement):
    from prechips.rules._profile import requirement_band

    return requirement_band(bundle(tmp_path, features), name, requirement)


def test_rocker_top_edge_profile_bands_its_concave_radius_and_height(tmp_path):
    loaded = bundle(tmp_path, {"top_edge": TOP_EDGE})
    from prechips.rules._profile import requirement_band

    # U0.5: the whole zone lies on the material side; adding material to the concave edge
    # shrinks the radius about its centre above and raises the edge over the pivot.
    radius, _ = requirement_band(loaded, "top_edge", "radius")
    height, _ = requirement_band(loaded, "top_edge", "height_above_pivot")
    assert radius == pytest.approx([799.5, 800.0])
    assert height == pytest.approx([8.0, 8.5])


def test_rocker_outer_profile_bands_its_bottom_radius(tmp_path):
    derived, _ = band(tmp_path, {"profile_outer": PROFILE_OUTER}, "profile_outer", "bottom_radius")
    # U0: the whole zone lies inside the material; material added grows the bottom radius.
    assert derived == pytest.approx([815.5, 816.0])


def test_convex_arc_radius_grows_with_added_material(tmp_path):
    # An outer boss: material added at its surface grows the radius about its BASIC centre.
    boss = (
        'kind = "boss"\nrequirements = ["radius", "surface_profile"]\nradius = 50.0\n'
        'surface_profile = 0.2\nsurface_profile_u = 0.05\nsurface_profile_datums = ["A"]\n'
        'surface_profile_governs = { radius = "increases" }\n'
    )
    derived, _ = band(tmp_path, {"boss": boss}, "boss", "radius")
    assert derived == pytest.approx([49.85, 50.05])


def test_an_omitted_disposition_is_equal_bilateral(tmp_path):
    top_edge = TOP_EDGE.replace("surface_profile_u = 0.5\n", "")
    derived, _ = band(tmp_path, {"top_edge": top_edge}, "top_edge", "radius")
    assert derived == pytest.approx([799.75, 800.25])


@pytest.mark.parametrize(
    ("sense", "expected"),
    [
        ("increases", [29.69493031919997, 30.20337978720002]),
        ("decreases", [29.79662021279998, 30.30506968080003]),
    ],
)
def test_an_oblique_reading_divides_each_offset_by_the_cosine(tmp_path, sense, expected):
    governs = f'{{ "tip:station" = {{ sense = "{sense}", obliquity_deg = 10.46 }} }}'
    features = {"tip": TIP_LAND, "zone": profile(governs, u="0.2")}
    derived, _ = band(tmp_path, features, "tip", "station")
    # 0.3 / cos 10.46° = 0.305070 below and 0.2 / cos 10.46° = 0.203380 above (increases).
    assert derived == pytest.approx(expected, abs=1e-9)
    straight = governs.replace("10.46", "0.0")
    plain, _ = band(
        tmp_path, {"tip": TIP_LAND, "zone": profile(straight, u="0.2")}, "tip", "station"
    )
    assert plain == pytest.approx([29.7, 30.2] if sense == "increases" else [29.8, 30.3])


@pytest.mark.parametrize("across", ['"tip_land"', "5.08"])
def test_a_planar_face_angle_tilts_by_the_zone_across_its_least_extent(tmp_path, across):
    governs = f'{{ "tip:land_angle_deg" = {{ tilt_across = {across} }} }}'
    features = {"tip": TIP_LAND, "zone": profile(governs)}
    derived, _ = band(tmp_path, features, "tip", "land_angle_deg")
    tilt = math.degrees(math.asin(0.5 / 5.08))
    assert tilt == pytest.approx(5.6485, abs=1e-4)
    assert derived == pytest.approx([10.46 - tilt, 10.46 + tilt], abs=1e-9)


@pytest.mark.parametrize("across", ["0.5", "0.4"])
def test_a_zone_no_narrower_than_the_face_bounds_no_tilt(tmp_path, across):
    governs = f'{{ "tip:land_angle_deg" = {{ tilt_across = {across} }} }}'
    derived, reason = band(
        tmp_path, {"tip": TIP_LAND, "zone": profile(governs)}, "tip", "land_angle_deg"
    )
    assert derived is None
    assert "face extent" in reason


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("surface_profile_u = 0.5", 'surface_profile_u = "unknown"', "disposition"),
        ("surface_profile = 0.5", 'surface_profile = "unknown"', "zone"),
        ('surface_profile_datums = ["A", "B", "C"]', "surface_profile_datums = []", "form only"),
        ('surface_profile_datums = ["A", "B", "C"]\n', "", "datum reference frame"),
        ('["A", "B", "C"]', '["A", "unknown"]', "datum reference frame"),
        ('radius = "decreases"', 'radius = "unknown"', "unknown"),
    ],
    ids=["unknown-u", "unknown-t", "empty-drf", "omitted-drf", "unknown-datum", "unknown-sense"],
)
def test_an_unresolved_profile_leaves_its_requirement_unknown(tmp_path, old, new, reason):
    derived, why = band(tmp_path, {"top_edge": TOP_EDGE.replace(old, new)}, "top_edge", "radius")
    assert derived is None
    assert reason in why


def test_a_tilt_across_a_face_of_unknown_least_extent_is_unknown(tmp_path):
    tip = TIP_LAND.replace("tip_land = [5.08, 6.1]", 'tip_land = ["unknown", 6.1]')
    governs = '{ "tip:land_angle_deg" = { tilt_across = "tip_land" } }'
    derived, why = band(tmp_path, {"tip": tip, "zone": profile(governs)}, "tip", "land_angle_deg")
    assert derived is None
    assert "least" in why


def test_several_profiles_governing_one_requirement_intersect(tmp_path):
    crown = profile('{ "top_edge:radius" = "increases" }', u="0.25")
    derived, why = band(tmp_path, {"top_edge": TOP_EDGE, "crown": crown}, "top_edge", "radius")
    # [799.5, 800.0] from top_edge's own zone, [799.75, 800.25] from crown's.
    assert derived == pytest.approx([799.75, 800.0])
    assert "top_edge" in why and "crown" in why


def test_one_unresolved_profile_among_several_leaves_the_requirement_unknown(tmp_path):
    crown = profile('{ "top_edge:radius" = "increases" }', u='"unknown"')
    derived, why = band(tmp_path, {"top_edge": TOP_EDGE, "crown": crown}, "top_edge", "radius")
    assert derived is None
    assert "crown" in why


def test_a_drawing_band_is_returned_as_drawn(tmp_path):
    derived, _ = band(tmp_path, {"tip": TIP_LAND}, "tip", "tip_land")
    assert derived == [5.08, 6.1]


def test_an_ungoverned_basic_scalar_has_no_band(tmp_path):
    derived, why = band(tmp_path, {"tip": TIP_LAND}, "tip", "station")
    assert derived is None
    assert "no band" in why


@pytest.mark.parametrize(
    ("features", "match"),
    [
        (
            {"top_edge": TOP_EDGE.replace('"height_above_pivot", ', "")},
            r"height_above_pivot is not a listed requirement of top_edge",
        ),
        (
            {"top_edge": TOP_EDGE.replace("radius = 800.0", "radius = [799.5, 800.0]")},
            r"top_edge radius must be a BASIC scalar",
        ),
        (
            {"top_edge": TOP_EDGE.replace("radius = 800.0", 'radius = "unknown"')},
            r"top_edge radius must be a BASIC scalar",
        ),
        (
            {"top_edge": TOP_EDGE.replace("surface_profile_u = 0.5", "surface_profile_u = 0.6")},
            r"surface_profile_u must lie in \[0, surface_profile\]",
        ),
        (
            {"top_edge": TOP_EDGE.replace("surface_profile_u = 0.5", "surface_profile_u = -0.1")},
            r"surface_profile_u must lie in \[0, surface_profile\]",
        ),
        (
            {"top_edge": TOP_EDGE.replace("surface_profile = 0.5", "surface_profile = 0.0")},
            r"surface_profile zone must be positive",
        ),
        (
            {
                "top_edge": TOP_EDGE.replace("surface_profile = 0.5\n", "").replace(
                    '"radius", "surface_profile"', '"radius"'
                )
            },
            r"surface_profile_datums, surface_profile_governs, surface_profile_u need a "
            r"surface_profile zone",
        ),
        (
            {"zone": profile('{ "nowhere:radius" = "increases" }')},
            r"names no manifest feature nowhere",
        ),
        (
            {"tip": TIP_LAND, "zone": profile('{ "tip:land_angle_deg" = "increases" }')},
            r"land_angle_deg is an angle: only tilt_across bounds it",
        ),
        (
            {"tip": TIP_LAND, "zone": profile('{ "tip:station" = { tilt_across = 5.08 } }')},
            r"tilt_across bounds only an angle",
        ),
        (
            {
                "tip": TIP_LAND,
                "zone": profile('{ "tip:land_angle_deg" = { tilt_across = "station" } }'),
            },
            r"tilt_across station is not a listed length band of tip",
        ),
        (
            {
                "tip": TIP_LAND,
                "zone": profile('{ "tip:land_angle_deg" = { tilt_across = 0.0 } }'),
            },
            r"tilt_across must be a positive face extent",
        ),
    ],
    ids=[
        "unlisted",
        "banded",
        "unknown-value",
        "u-above-t",
        "negative-u",
        "zero-zone",
        "governs-without-zone",
        "missing-feature",
        "sense-on-angle",
        "tilt-on-length",
        "tilt-across-scalar",
        "tilt-across-zero",
    ],
)
def test_a_malformed_profile_is_bad_input(tmp_path, features, match):
    with pytest.raises(BadInput, match=match):
        bundle(tmp_path, features)


@pytest.mark.parametrize("obliquity", ["90.0", "95.0", "-1.0"])
def test_an_obliquity_outside_zero_to_ninety_degrees_is_bad_input(tmp_path, obliquity):
    governs = f'{{ "tip:station" = {{ sense = "increases", obliquity_deg = {obliquity} }} }}'
    with pytest.raises(BadInput, match=r"obliquity_deg must lie in \[0, 90\)"):
        bundle(tmp_path, {"tip": TIP_LAND, "zone": profile(governs)})


def test_a_governed_band_requirement_exits_three_before_outputs(tmp_path):
    top_edge = TOP_EDGE.replace("radius = 800.0", "radius = [799.5, 800.0]")
    plan = write_bundle(tmp_path, {"top_edge": top_edge})
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out)
    assert result.returncode == 3, result.stderr
    assert "must be a BASIC scalar" in " ".join(result.stderr.split())
    assert not out.exists() or not tuple(out.iterdir())


def inspection_finding(loaded, subject):
    return next(row for row in inspection.evaluate(loaded) if row.subject == subject)


def test_inspection_reads_a_governed_radius_against_its_derived_band(tmp_path):
    loaded = bundle(tmp_path, {"top_edge": TOP_EDGE})
    row = inspection_finding(loaded, "top_edge:radius")
    assert row.numbers["limits"] == pytest.approx([799.5, 800.0])
    assert row.numbers["band_mm"] == pytest.approx(0.5)
    assert row.status == "pass", row.sentence


def test_inspection_of_an_unresolved_governed_radius_stays_unknown(tmp_path):
    top_edge = TOP_EDGE.replace("surface_profile_u = 0.5", 'surface_profile_u = "unknown"')
    row = inspection_finding(bundle(tmp_path, {"top_edge": top_edge}), "top_edge:radius")
    assert row.status == "unknown"
    assert row.numbers["limits"] == "unknown"
    assert "disposition" in row.numbers["profile_band"]


def test_a_process_hold_on_a_governed_radius_lies_inside_its_derived_band(tmp_path):
    hold = (
        'process_holds = [{ feature = "top_edge", requirement = "radius", '
        'band = [799.6, 799.9], gauge = "gauge", reason = "rocker fit" }]\n'
    )
    loaded = bundle(tmp_path, {"top_edge": TOP_EDGE}, holds=hold)
    (row,) = inspection.process_holds(
        loaded, loaded.plan["setups"][1], loaded.plan["setups"][1]["ops"][0]
    ).numbers["process_holds"]
    assert row["drawing_band"] == pytest.approx([799.5, 800.0])
    assert row["inside_drawing_band"] is True


@pytest.mark.parametrize(
    ("gauge", "method", "status"),
    [
        ("cmm", METHOD, "pass"),
        ("cmm", None, "unknown"),
        ("cmm", '"unknown"', "unknown"),
        ("caliper", METHOD, "error"),
    ],
)
def test_the_profile_zone_is_inspected_like_a_position_zone(tmp_path, gauge, method, status):
    path = write_bundle(
        tmp_path, {"top_edge": TOP_EDGE}, requirement="surface_profile", gauge=gauge, method=method
    )
    row = inspection_finding(load_bundle(path), "top_edge:surface_profile")
    assert row.status == status, row.sentence
    assert row.numbers["limits"] == 0.5
    if status != "error":
        assert row.numbers["inspection_method"] == (method.strip('"') if method else "unknown")


# The concave R30 dish of the manual-arc tests, its radius BASIC under a U0.5 profile.
DISH_BASIC = (
    "kind = 'profile'\nrequirements = ['radius', 'surface_profile']\nradius = 30.0\n"
    "arc_centre = [20.0, 40.0, 0.0]\nend = [38.0, 16.0]\n"
    "surface_profile = 0.2\nsurface_profile_u = 0.2\nsurface_profile_datums = ['A']\n"
    "surface_profile_governs = { radius = 'decreases' }\n"
    "[datums.A]\nfeature = 'bore'\n"
)


def test_file_to_line_proves_its_line_against_a_governed_radius_band(tmp_path):
    row = manual_row(scratch(tmp_path, TEMPLATE_FILING, target=DISH_BASIC), 30)
    assert row.numbers["radius_band_mm"] == pytest.approx([29.8, 30.0])
    assert "drawing radius band is unknown" not in " ".join(row.numbers.get("debts", []))


def test_file_to_line_on_an_ungoverned_basic_radius_keeps_its_band_debt(tmp_path):
    basic = DISH_BASIC.replace("surface_profile_governs = { radius = 'decreases' }\n", "")
    row = manual_row(scratch(tmp_path, TEMPLATE_FILING, target=basic), 30)
    assert row.numbers["radius_band_mm"] == "unknown"
    assert "drawing radius band is unknown" in " ".join(row.numbers["debts"])


def datum_finding(loaded, name="top_edge"):
    return next(row for row in datum_consistency.evaluate(loaded) if row.subject == name)


@pytest.mark.parametrize(("budget", "status"), [("0.10", "pass"), ("0.60", "error")])
def test_datum_consistency_relates_the_profile_datums_and_its_height_band(tmp_path, budget, status):
    top_edge = TOP_EDGE + 'height_from = "base"\n'
    row = datum_finding(bundle(tmp_path, {"top_edge": top_edge}, budget=budget))
    relationships = row.numbers["relationships"]
    assert [item["datum"] for item in relationships] == ["A", "B", "C", "base"]
    # The zone t for each DRF datum; the derived [8.0, 8.5] height band's width from base.
    assert [item["tolerance_mm"] for item in relationships] == pytest.approx([0.5] * 4)
    assert row.numbers["surface_profile_datums"] == ["A", "B", "C"]
    assert row.status == status


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("surface_profile = 0.5", 'surface_profile = "unknown"'),
        ('surface_profile_datums = ["A", "B", "C"]\n', ""),
    ],
    ids=["unknown-zone", "omitted-drf"],
)
def test_datum_consistency_of_an_unresolved_profile_is_unknown(tmp_path, old, new):
    row = datum_finding(bundle(tmp_path, {"top_edge": TOP_EDGE.replace(old, new)}))
    assert row.status == "unknown"


def test_a_form_only_profile_relates_no_datum(tmp_path):
    top_edge = TOP_EDGE.replace('["A", "B", "C"]', "[]")
    assert datum_finding(bundle(tmp_path, {"top_edge": top_edge})).status == "not_applicable"
