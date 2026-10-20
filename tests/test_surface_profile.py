"""Surface-profile zones give the BASIC dimensions they govern a band (HA#1544).

An ASME Y14.5 SURFACE PROFILE ``t`` (``U`` of it on the material-added side) to a datum
reference frame holds every point of the surface inside the zone about its BASIC true
profile. A BASIC length read along the surface normal therefore reads inside a pointwise
band, and a BASIC angle of a planar face tilts at most ``asin(t / l_min)``. Anything the
zone cannot locate stays unknown, never a pass.
"""

import json
import math
from pathlib import Path

import pytest
from test_cli import run_cli
from test_manual_arc import TEMPLATE_FILING, manual_row, scratch

from prechips.inputs import BadInput, load_bundle
from prechips.rules import datum_consistency, inspection

ROCKER = Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml"
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


def profile(
    governs, *, zone="0.5", u="0.5", datums='["A", "B", "C"]', requirements='["surface_profile"]'
):
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
    """S1 finishes datums; S2 forms every other feature before the final capability check.

    These fixtures test gauge/profile capability, not preservation through later cuts.
    """
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
    procedure = f"inspection_methods = {{ {requirement} = {method} }}\n" if method else ""
    finishing = "".join(
        f'[[setups.ops]]\nop = {40 + 10 * index}\ndo = "profile"\nfeature = "{name}"\n'
        + (procedure + holds if name == subject and holds else "")
        for index, name in enumerate(features)
    )
    if subject in features:
        finishing += (
            f'[[setups.ops]]\nop = {40 + 10 * len(features)}\ndo = "inspect"\n'
            f'feature = "{subject}"\nchecks = {{ {requirement} = "gauge" }}\n' + procedure
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


@pytest.mark.parametrize(
    ("sense", "u", "expected"),
    [
        # A boss (convex): added material grows the diameter by twice the radial offset.
        ("increases", "0.2", [20.0, 20.4]),
        ("increases", "0.0", [19.6, 20.0]),
        ("increases", "0.1", [19.8, 20.2]),
        # A bore (concave): added material shrinks the diameter.
        ("decreases", "0.2", [19.6, 20.0]),
        ("decreases", "0.0", [20.0, 20.4]),
    ],
)
def test_a_governed_basic_diameter_moves_on_both_sides(tmp_path, sense, u, expected):
    cylinder = (
        'kind = "boss"\nrequirements = ["dia", "surface_profile"]\ndia = 20.0\n'
        f'surface_profile = 0.2\nsurface_profile_u = {u}\nsurface_profile_datums = ["A"]\n'
        f'surface_profile_governs = {{ dia = "{sense}" }}\n'
    )
    derived, _ = band(tmp_path, {"cylinder": cylinder}, "cylinder", "dia")
    assert derived == pytest.approx(expected)


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
        (
            {"top_edge": TOP_EDGE.replace('"radius", "surface_profile"', '"radius"')},
            r"top_edge: a surface_profile zone must be listed in its requirements",
        ),
        (
            {"top_edge": TOP_EDGE.replace(TOP_EDGE.splitlines()[1], 'requirements = "unknown"')},
            r"top_edge: a surface_profile zone must be listed in its requirements",
        ),
        (
            {
                "dome": 'kind = "boss"\nrequirements = ["dome_height", "surface_profile"]\n'
                'dome_height = 3.0\nsurface_profile = 0.5\nsurface_profile_datums = ["A"]\n'
                'surface_profile_governs = { dome_height = "increases" }\n'
            },
            r"dome_height is not a BASIC dimension the inspection rule reads",
        ),
        (
            {
                "bore": 'kind = "hole"\nrequirements = ["position_dia", "surface_profile"]\n'
                'position_dia = 0.2\nsurface_profile = 0.5\nsurface_profile_datums = ["A"]\n'
                'surface_profile_governs = { position_dia = "decreases" }\n'
            },
            r"position_dia is not a BASIC dimension the inspection rule reads",
        ),
        (
            {"top_edge": TOP_EDGE.replace('["A", "B", "C"]', '["A", "B", "D"]')},
            r"top_edge: surface_profile_datums D is not a declared datum",
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
        "unlisted-zone",
        "unknown-requirements",
        "uninspected-target",
        "zone-target",
        "undeclared-datum",
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
    ("kind", "sense", "gauge", "limits", "status"),
    [
        ("boss", "increases", "caliper", [20.0, 20.4], "pass"),
        # An external micrometer never measures a bore, whichever diameter names it.
        ("hole", "decreases", "micrometer", [19.6, 20.0], "error"),
    ],
)
def test_inspection_reads_a_governed_nominal_diameter_against_its_derived_band(
    tmp_path, kind, sense, gauge, limits, status
):
    cylinder = (
        f'kind = "{kind}"\nrequirements = ["nominal_dia", "surface_profile"]\n'
        "nominal_dia = 20.0\nsurface_profile = 0.2\nsurface_profile_u = 0.2\n"
        'surface_profile_datums = ["A"]\n'
        f'surface_profile_governs = {{ nominal_dia = "{sense}" }}\n'
    )
    loaded = bundle(
        tmp_path, {"cylinder": cylinder}, subject="cylinder", requirement="nominal_dia", gauge=gauge
    )
    row = inspection_finding(loaded, "cylinder:nominal_dia")
    assert row.numbers["limits"] == pytest.approx(limits)
    assert row.status == status, row.sentence


TILT = '{ "tip:land_angle_deg" = { tilt_across = "tip_land" } }'


@pytest.mark.parametrize(
    ("zone", "band_mm", "status"),
    [
        # t 0.5 across the 5.08 least land: 10.46 ± 5.65°, read end to end as 2t = 1.0 mm.
        ("0.5", 1.0, "pass"),
        # t 0.004: ± 0.045°. Read as millimetres, that 0.09 band passes the 0.01 gauge; the
        # linear zone it is, 2t = 0.008 mm, is finer than the gauge resolves.
        ("0.004", 0.008, "error"),
    ],
)
def test_a_tilt_across_angle_is_inspected_as_the_linear_zone_across_its_length(
    tmp_path, zone, band_mm, status
):
    features = {"tip": TIP_LAND, "zone": profile(TILT, zone=zone, u=None)}
    loaded = bundle(tmp_path, features, subject="tip", requirement="land_angle_deg")
    row = inspection_finding(loaded, "tip:land_angle_deg")
    tilt = math.degrees(math.asin(float(zone) / 5.08))
    assert row.numbers["limits"] == pytest.approx([10.46 - tilt, 10.46 + tilt])
    assert row.numbers["tilt_across_length"] == 5.08
    assert row.numbers["band_mm"] == pytest.approx(band_mm)
    assert row.status == status, row.sentence


def test_the_tilts_linear_zone_is_judged_on_resolution_never_on_the_gauge_span(tmp_path):
    # harmonic-analyzer's outline template is cut to radii 8-817: it spans no size near the
    # 0-1.0 mm deviation, which it still reads end to end against its edge.
    features = {"tip": TIP_LAND, "zone": profile(TILT)}
    path = write_bundle(tmp_path, features, subject="tip", requirement="land_angle_deg")
    inventory = tmp_path / "inventory.toml"
    text = inventory.read_text(encoding="utf-8")
    assert "range_mm = [0.0, 1000.0]" in text
    inventory.write_text(text.replace("[0.0, 1000.0]", "[8.0, 817.0]"), encoding="utf-8")
    row = inspection_finding(load_bundle(path), "tip:land_angle_deg")
    assert row.numbers["range_mm"] == [8.0, 817.0]
    assert row.numbers["band_mm"] == pytest.approx(1.0)
    assert row.status == "pass", row.sentence


def test_a_process_hold_on_a_tilt_across_angle_reads_its_linear_zone(tmp_path):
    hold = (
        'process_holds = [{ feature = "tip", requirement = "land_angle_deg", '
        'band = [10.0, 11.0], gauge = "gauge", reason = "land square fit" }]\n'
    )
    loaded = bundle(
        tmp_path,
        {"tip": TIP_LAND, "zone": profile(TILT)},
        subject="tip",
        requirement="land_angle_deg",
        holds=hold,
    )
    (row,) = inspection.process_holds(
        loaded, loaded.plan["setups"][1], loaded.plan["setups"][1]["ops"][0]
    ).numbers["process_holds"]
    across = 5.08 * (math.sin(math.radians(11.0 - 10.46)) - math.sin(math.radians(10.0 - 10.46)))
    assert row["inside_drawing_band"] is True
    assert row["tilt_across_length"] == 5.08
    assert row["band_mm"] == pytest.approx(across)
    assert row["gauge_status"] == "pass", row["gauge_message"]


def test_an_angle_band_with_no_tilt_length_has_no_angular_gauge_capability(tmp_path):
    tip = TIP_LAND.replace("land_angle_deg = 10.46", "land_angle_deg = [89.0, 91.0]")
    loaded = bundle(tmp_path, {"tip": tip}, subject="tip", requirement="land_angle_deg")
    row = inspection_finding(loaded, "tip:land_angle_deg")
    assert row.status == "unknown"
    assert row.sentence == "tip land_angle_deg: no angular gauge capability."
    assert "band_mm" not in row.numbers


def test_profiles_tilting_one_angle_across_different_lengths_leave_it_unknown(tmp_path):
    crown = profile('{ "tip:land_angle_deg" = { tilt_across = 6.0 } }', zone="0.6")
    features = {"tip": TIP_LAND, "zone": profile(TILT), "crown": crown}
    loaded = bundle(tmp_path, features, subject="tip", requirement="land_angle_deg")
    row = inspection_finding(loaded, "tip:land_angle_deg")
    assert row.status == "unknown"
    assert row.numbers["tilt_across_length"] == "unknown"
    assert "different lengths" in row.numbers["tilt_across_reason"]


def drawn_tip(across, band="[89.0, 91.0]"):
    """The tip land with its angle drawn as ``band``, read across ``across``."""
    tip = TIP_LAND.replace("land_angle_deg = 10.46", f"land_angle_deg = {band}")
    return tip + f"tilt_across = {{ land_angle_deg = {across} }}\n"


@pytest.mark.parametrize("across", ['"tip_land"', "5.08"])
@pytest.mark.parametrize(
    ("drawn", "half", "status"),
    [
        # 90 ± 1° across the 5.08 least land, about its mid angle: 2 · 5.08 · sin 1° = 0.18.
        ("[89.0, 91.0]", 1.0, "pass"),
        # 90 ± 0.05°: a 0.1 band were degrees millimetres, which the 0.01 gauge resolves; the
        # linear zone it is, 2 · 5.08 · sin 0.05° = 0.0089, is finer than the gauge reads.
        ("[89.95, 90.05]", 0.05, "error"),
    ],
)
def test_a_drawn_angle_band_read_across_its_face_is_judged_as_its_linear_zone(
    tmp_path, across, drawn, half, status
):
    tip = drawn_tip(across, drawn)
    loaded = bundle(tmp_path, {"tip": tip}, subject="tip", requirement="land_angle_deg")
    row = inspection_finding(loaded, "tip:land_angle_deg")
    assert row.numbers["limits"] == json.loads(drawn)
    assert row.numbers["tilt_across_length"] == 5.08
    assert row.numbers["band_mm"] == pytest.approx(2 * 5.08 * math.sin(math.radians(half)))
    assert row.status == status, row.sentence


def test_a_process_hold_on_a_drawn_angle_band_reads_its_linear_zone(tmp_path):
    hold = (
        'process_holds = [{ feature = "tip", requirement = "land_angle_deg", '
        'band = [89.5, 90.5], gauge = "gauge", reason = "land square fit" }]\n'
    )
    loaded = bundle(
        tmp_path,
        {"tip": drawn_tip('"tip_land"')},
        subject="tip",
        requirement="land_angle_deg",
        holds=hold,
    )
    (row,) = inspection.process_holds(
        loaded, loaded.plan["setups"][1], loaded.plan["setups"][1]["ops"][0]
    ).numbers["process_holds"]
    assert row["inside_drawing_band"] is True
    assert row["tilt_across_length"] == 5.08
    assert row["band_mm"] == pytest.approx(2 * 5.08 * math.sin(math.radians(0.5)))
    assert row["gauge_status"] == "pass", row["gauge_message"]


@pytest.mark.parametrize("land", ["[0.0, 6.1]", "[-5.08, 6.1]"])
def test_an_angle_read_across_a_face_of_no_positive_least_extent_is_unknown(tmp_path, land):
    tip = drawn_tip('"tip_land"').replace("tip_land = [5.08, 6.1]", f"tip_land = {land}")
    loaded = bundle(tmp_path, {"tip": tip}, subject="tip", requirement="land_angle_deg")
    row = inspection_finding(loaded, "tip:land_angle_deg")
    assert row.status == "unknown", row.sentence
    assert row.numbers["tilt_across_length"] == "unknown"
    assert "no positive face extent" in row.numbers["tilt_across_reason"]


@pytest.mark.parametrize("land", ["tip_land_pos_x", "tip_land_neg_x"])
def test_the_rocker_tip_land_angle_reads_as_its_linear_zone_across_the_land(land):
    row = inspection_finding(load_bundle(ROCKER), f"{land}:land_angle_deg")
    # The drawn 90 ± 1° across the 5.08 least land: 2 · 5.08 · sin 1° = 0.177 mm, which the
    # rocker profile template's 0.05 resolution reads.
    assert row.numbers["limits"] == [89.0, 91.0]
    assert row.numbers["tilt_across_length"] == 5.08
    assert row.numbers["band_mm"] == pytest.approx(2 * 5.08 * math.sin(math.radians(1.0)))
    assert row.status == "pass", row.sentence


@pytest.mark.parametrize(
    ("tip", "match"),
    [
        (
            drawn_tip('"tip_land"').replace('"land_angle_deg", ', ""),
            r"tip: tilt_across land_angle_deg is not a listed angle \(_deg\) requirement",
        ),
        (
            TIP_LAND + "tilt_across = { tip_land = 5.08 }\n",
            r"tip: tilt_across tip_land is not a listed angle \(_deg\) requirement",
        ),
        (
            TIP_LAND + 'tilt_across = { land_angle_deg = "tip_land" }\n',
            r"tip: tilt_across land_angle_deg: only a drawn angle band reads across a face",
        ),
        (drawn_tip('"station"'), r"tilt_across station is not a listed length band of tip"),
        (drawn_tip("0.0"), r"tip: tilt_across land_angle_deg: tilt_across must be a positive"),
    ],
    ids=["unlisted-angle", "length", "basic-angle", "non-band-length", "zero-length"],
)
def test_a_malformed_drawn_angle_length_is_bad_input(tmp_path, tip, match):
    with pytest.raises(BadInput, match=match):
        bundle(tmp_path, {"tip": tip})


# Listed bands that are no face extent: a roughness and a geometric zone.
NOT_LENGTHS = {"finish_ra": "[0.4, 1.6]", "position_dia": "[0.0, 0.2]"}


def listing(tip, requirement):
    """``tip`` also listing ``requirement`` as its ``NOT_LENGTHS`` band."""
    listed = tip.replace('requirements = ["', f'requirements = ["{requirement}", "')
    return listed + f"{requirement} = {NOT_LENGTHS[requirement]}\n"


@pytest.mark.parametrize("extent", sorted(NOT_LENGTHS))
@pytest.mark.parametrize("form", ["profile", "drawn"])
def test_a_tilt_read_across_a_listed_band_that_is_no_length_is_bad_input(tmp_path, form, extent):
    if form == "profile":
        governs = f'{{ "tip:land_angle_deg" = {{ tilt_across = "{extent}" }} }}'
        features = {"tip": listing(TIP_LAND, extent), "zone": profile(governs)}
    else:
        features = {"tip": listing(drawn_tip(f'"{extent}"'), extent)}
    with pytest.raises(BadInput, match=rf"tilt_across {extent} is not a listed length band of tip"):
        bundle(tmp_path, features)


# Named extents that are no two-limit band: one limit, three, reversed, a non-finite or a
# non-numeric limit.
MALFORMED_BANDS = [
    "[5.08]",
    "[1.0, 2.0, 3.0]",
    "[6.1, 5.08]",
    "[nan, 1.0]",
    "[1.0, inf]",
    '["wide", 6.1]',
]
# The same shapes as drawn angle bands.
MALFORMED_ANGLES = [
    "[89.0]",
    "[89.0, 90.0, 91.0]",
    "[91.0, 89.0]",
    "[nan, 91.0]",
    "[89.0, inf]",
    '["square", 91.0]',
]


@pytest.mark.parametrize("land", MALFORMED_BANDS)
@pytest.mark.parametrize("form", ["profile", "drawn"])
def test_a_tilt_read_across_a_malformed_extent_band_is_bad_input(tmp_path, form, land):
    if form == "profile":
        governs = '{ "tip:land_angle_deg" = { tilt_across = "tip_land" } }'
        features = {"tip": TIP_LAND, "zone": profile(governs)}
    else:
        features = {"tip": drawn_tip('"tip_land"')}
    features["tip"] = features["tip"].replace("tip_land = [5.08, 6.1]", f"tip_land = {land}")
    with pytest.raises(BadInput, match="tip_land"):
        bundle(tmp_path, features)


@pytest.mark.parametrize("drawn", MALFORMED_ANGLES)
def test_a_malformed_drawn_angle_band_read_across_a_face_is_bad_input(tmp_path, drawn):
    with pytest.raises(BadInput, match="land_angle_deg"):
        bundle(tmp_path, {"tip": drawn_tip('"tip_land"', drawn)})


def test_a_drawn_angle_band_with_an_unknown_limit_loads_and_stays_unknown(tmp_path):
    tip = drawn_tip('"tip_land"', '["unknown", 91.0]')
    loaded = bundle(tmp_path, {"tip": tip}, subject="tip", requirement="land_angle_deg")
    assert inspection_finding(loaded, "tip:land_angle_deg").status == "unknown"


@pytest.mark.parametrize("form", ["profile", "drawn"])
def test_a_tilt_extent_band_with_an_unknown_limit_loads_and_stays_unknown(tmp_path, form):
    tip = TIP_LAND if form == "profile" else drawn_tip('"tip_land"')
    tip = tip.replace("tip_land = [5.08, 6.1]", 'tip_land = [5.08, "unknown"]')
    governs = '{ "tip:land_angle_deg" = { tilt_across = "tip_land" } }'
    features = {"tip": tip, "zone": profile(governs)} if form == "profile" else {"tip": tip}
    loaded = bundle(tmp_path, features, subject="tip", requirement="land_angle_deg")
    row = inspection_finding(loaded, "tip:land_angle_deg")
    assert row.status == "unknown", row.sentence
    assert row.numbers["tilt_across_length"] == "unknown"


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


@pytest.mark.parametrize(
    ("datums", "status"),
    [
        (None, "unknown"),
        ('"unknown"', "unknown"),
        ('["A", "unknown"]', "unknown"),
        ("[]", "pass"),
        ('["A"]', "pass"),
    ],
    ids=["omitted", "unknown", "unknown-datum", "form-only", "known"],
)
def test_the_profile_zone_passes_only_in_a_declared_datum_frame(tmp_path, datums, status):
    drf = 'surface_profile_datums = ["A", "B", "C"]\n'
    top_edge = TOP_EDGE.replace(
        drf, "" if datums is None else f"surface_profile_datums = {datums}\n"
    )
    path = write_bundle(
        tmp_path, {"top_edge": top_edge}, requirement="surface_profile", gauge="cmm"
    )
    row = inspection_finding(load_bundle(path), "top_edge:surface_profile")
    assert row.status == status, row.sentence
    expected = "unknown" if datums is None else json.loads(datums)
    assert row.numbers["surface_profile_datums"] == expected


DATUMS = (
    '[datums.A]\nfeature = "base"\n[datums.B]\nfeature = "axis"\n[datums.C]\nfeature = "side"\n'
)
# A declared datum label that names no manifest feature, as manifest rewrites.
UNRESOLVED_DATUMS = {
    "unknown-feature": [('[datums.C]\nfeature = "side"\n', '[datums.C]\nfeature = "unknown"\n')],
    "absent-feature": [('[datums.C]\nfeature = "side"\n', '[datums.C]\nfeature = "ghost"\n')],
    "no-feature": [('[datums.C]\nfeature = "side"\n', '[datums.C]\nsurface = "side face"\n')],
    "unknown-datum": [('[datums.A]\nfeature = "base"\n', '[datums]\nA = "unknown"\n')],
    "unknown-table": [
        (DATUMS, ""),
        ('frames = "unknown"\n', 'frames = "unknown"\ndatums = "unknown"\n'),
    ],
}


def rewrite_manifest(path, edits):
    """Apply ``(old, new)`` edits, each matching once, to the bundle's features.toml."""
    manifest = path.parent / "features.toml"
    text = manifest.read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    manifest.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("edits", UNRESOLVED_DATUMS.values(), ids=UNRESOLVED_DATUMS.keys())
def test_a_profile_datum_naming_no_manifest_feature_leaves_its_bands_unknown(tmp_path, edits):
    from prechips.rules._profile import requirement_band

    loaded = load_bundle(rewrite_manifest(write_bundle(tmp_path, {"top_edge": TOP_EDGE}), edits))
    derived, reason = requirement_band(loaded, "top_edge", "radius")
    assert derived is None
    assert "the datum reference frame is unknown" in reason
    assert inspection_finding(loaded, "top_edge:radius").status == "unknown"


@pytest.mark.parametrize("edits", UNRESOLVED_DATUMS.values(), ids=UNRESOLVED_DATUMS.keys())
def test_a_profile_zone_whose_datum_names_no_manifest_feature_is_unknown(tmp_path, edits):
    path = write_bundle(
        tmp_path, {"top_edge": TOP_EDGE}, requirement="surface_profile", gauge="cmm"
    )
    row = inspection_finding(load_bundle(rewrite_manifest(path, edits)), "top_edge:surface_profile")
    assert row.status == "unknown", row.sentence


def test_a_profile_datum_a_feature_declares_resolves_its_frame(tmp_path):
    from prechips.rules._profile import requirement_band

    path = write_bundle(
        tmp_path, {"top_edge": TOP_EDGE}, requirement="surface_profile", gauge="cmm"
    )
    edits = [
        ('[datums.C]\nfeature = "side"\n', ""),
        ('[features.side]\nkind = "face"\n', '[features.side]\nkind = "face"\ndatum = "C"\n'),
    ]
    loaded = load_bundle(rewrite_manifest(path, edits))
    assert inspection_finding(loaded, "top_edge:surface_profile").status == "pass"
    assert requirement_band(loaded, "top_edge", "radius")[0] == pytest.approx([799.5, 800.0])


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


def test_file_to_line_halves_a_governed_basic_diameter_band(tmp_path):
    boss = (
        "kind = 'boss'\nrequirements = ['dia', 'surface_profile']\nat = [20.0, 10.0, 0.0]\n"
        "dia = 20.0\nsurface_profile = 0.2\nsurface_profile_u = 0.2\n"
        "surface_profile_datums = ['A']\nsurface_profile_governs = { dia = 'increases' }\n"
        "[datums.A]\nfeature = 'bore'\n"
    )
    row = manual_row(scratch(tmp_path, TEMPLATE_FILING, target=boss), 30)
    # Ø[20.0, 20.4] from a U0.2 zone: the rim lies 0 to 0.2 outside R10.
    assert row.numbers["radius_band_mm"] == pytest.approx([10.0, 10.2])


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


def test_datum_consistency_reads_an_inch_profile_zone_in_millimetres(tmp_path):
    top_edge = (
        TOP_EDGE.replace("surface_profile = 0.5", "surface_profile = 0.02").replace(
            "surface_profile_u = 0.5", "surface_profile_u = 0.02"
        )
        + 'height_from = "base"\n'
    )
    path = write_bundle(tmp_path, {"top_edge": top_edge}, budget="0.10")
    manifest = tmp_path / "features.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace('units = "mm"', 'units = "in"'),
        encoding="utf-8",
    )
    row = datum_finding(load_bundle(path))
    # 0.02 in = 0.508 mm, above the 0.10 mm budget: the zone and its [8.0, 8.02] in height
    # band both read 0.508 mm.
    tolerances = [item["tolerance_mm"] for item in row.numbers["relationships"]]
    assert tolerances == pytest.approx([0.508] * 4)
    assert row.status == "pass", row.sentence


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


# One profile naming its own requirement twice, as a bare and a qualified key (Audit238).
@pytest.mark.parametrize("again", ['"increases"', '"decreases"'], ids=["contradictory", "same"])
def test_a_profile_governing_one_target_twice_is_bad_input(tmp_path, again):
    top_edge = TOP_EDGE.replace("surface_profile_u = 0.5", "surface_profile_u = 0.4").replace(
        'surface_profile_governs = { radius = "decreases", height_above_pivot = "increases" }',
        f'surface_profile_governs = {{ radius = "decreases", "top_edge:radius" = {again} }}',
    )
    with pytest.raises(BadInput, match=r"radius and top_edge:radius both govern top_edge radius"):
        bundle(tmp_path, {"top_edge": top_edge})


def cylinder(requirement, entry):
    """A BASIC Ø20 boss whose own profile governs ``requirement`` with ``entry``."""
    return (
        f'kind = "boss"\nrequirements = ["{requirement}", "surface_profile"]\n'
        f"{requirement} = 20.0\nsurface_profile = 0.2\nsurface_profile_u = 0.2\n"
        'surface_profile_datums = ["A"]\n'
        f"surface_profile_governs = {{ {requirement} = {entry} }}\n"
    )


OBLIQUE = '{ sense = "increases", obliquity_deg = 75.0 }'


# A length read along the normal through a centre has no oblique reading (Audit238).
@pytest.mark.parametrize(
    ("features", "requirement"),
    [
        (
            {
                "top_edge": TOP_EDGE.replace(
                    'radius = "decreases"', 'radius = { sense = "decreases", obliquity_deg = 60.0 }'
                )
            },
            "radius",
        ),
        (
            {
                "top_edge": TOP_EDGE.replace(
                    'radius = "decreases"', 'radius = { sense = "decreases", obliquity_deg = 89.9 }'
                )
            },
            "radius",
        ),
        (
            {"outer": PROFILE_OUTER.replace('"increases"', OBLIQUE)},
            "bottom_radius",
        ),
        ({"cyl": cylinder("dia", OBLIQUE)}, "dia"),
        ({"cyl": cylinder("nominal_dia", OBLIQUE)}, "nominal_dia"),
    ],
    ids=["radius-60", "radius-89.9", "bottom_radius", "dia", "nominal_dia"],
)
def test_an_oblique_reading_of_a_centred_length_is_bad_input(tmp_path, features, requirement):
    with pytest.raises(BadInput, match=rf"{requirement} is read along the normal through"):
        bundle(tmp_path, features)


def test_a_centred_length_read_at_zero_obliquity_reads_normally(tmp_path):
    top_edge = TOP_EDGE.replace(
        'radius = "decreases"', 'radius = { sense = "decreases", obliquity_deg = 0.0 }'
    )
    assert band(tmp_path, {"top_edge": top_edge}, "top_edge", "radius")[0] == pytest.approx(
        [799.5, 800.0]
    )


# A frame naming the profiled feature itself, by its own datum or the datums table (Audit238).
@pytest.mark.parametrize(
    "edits",
    [
        [
            (
                'surface_profile_datums = ["A", "B", "C"]\n',
                'surface_profile_datums = ["P"]\ndatum = "P"\n',
            )
        ],
        [('[datums.A]\nfeature = "base"\n', '[datums.A]\nfeature = "top_edge"\n')],
        [
            (
                'surface_profile_datums = ["A", "B", "C"]\n',
                'surface_profile_datums = ["A", "B", "C"]\ndatum = "A"\n',
            )
        ],
    ],
    ids=["own-datum", "table", "own-datum-over-table"],
)
def test_a_profile_referenced_to_its_own_feature_is_bad_input(tmp_path, edits):
    path = rewrite_manifest(write_bundle(tmp_path, {"top_edge": TOP_EDGE}), edits)
    with pytest.raises(BadInput, match=r"top_edge: surface_profile_datums \w is top_edge's own"):
        load_bundle(path)


@pytest.mark.parametrize("datums", ['["A", "A", "A"]', '["A", "B", "A"]'])
def test_a_datum_named_twice_in_a_profile_frame_is_bad_input(tmp_path, datums):
    top_edge = TOP_EDGE.replace('["A", "B", "C"]', datums)
    with pytest.raises(BadInput, match=r"top_edge: surface_profile_datums A is named twice"):
        bundle(tmp_path, {"top_edge": top_edge})


def test_unknown_labels_in_a_profile_frame_are_not_duplicates(tmp_path):
    top_edge = TOP_EDGE.replace('["A", "B", "C"]', '["A", "unknown", "unknown"]')
    derived, why = band(tmp_path, {"top_edge": top_edge}, "top_edge", "radius")
    assert derived is None
    assert "the datum reference frame is unknown" in why
