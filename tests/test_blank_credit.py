"""A blank bought already profiled (#248): schema, inputs, cache identity and face credit.

The FreeCAD tests use the frozen ``examples/geometry/profiled-blank`` solids: the finished
strap (its corner chamfered) and its laser-cut blank (that corner left square).
"""

import hashlib
import math
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_kernel_geometry import Engine

from prechips import kernel
from prechips.inputs import BadInput, Bundle, load_bundle
from prechips.model import Inventory, Plan
from prechips.rules import blank_credit, coverage
from prechips.sheet import _Traveler

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "geometry" / "profiled-blank"
PLATE, BLANK = FIXTURE / "strap-plate.STEP", FIXTURE / "strap-blank.STEP"
BLANK_SHA = hashlib.sha256(BLANK.read_bytes()).hexdigest()
BOTTOM_EDGE, CHAMFER, RIGHT_END = (
    "#17/ADVANCED_FACE[1]/",
    "#57/ADVANCED_FACE[2]/",
    "#88/ADVANCED_FACE[3]/",
)
ARC, LEFT_END, BOTTOM, TOP = (
    "#119/ADVANCED_FACE[4]/",
    "#152/ADVANCED_FACE[5]/",
    "#174/ADVANCED_FACE[6]/",
    "#187/ADVANCED_FACE[7]/",
)
FACES = [BOTTOM_EDGE, CHAMFER, RIGHT_END, ARC, LEFT_END, BOTTOM, TOP]
BLANK_RECORD = {
    "step": "strap-blank.STEP",
    "step_sha256": BLANK_SHA,
    "profile_tolerance_mm": 0.127,
    "cite": "vendor tolerance (test)",
}


# --------------------------------------------------------------------------- schema


def _plan(stock):
    return {"part": "p", "features": "features.toml", "setups": [], "stock": stock}


def test_a_profiled_blank_is_a_root_stock_or_a_component():
    root = Plan.model_validate(_plan({"form": "profiled_blank", "blank": BLANK_RECORD}))
    assert root.model_dump(exclude_unset=True)["stock"]["blank"] == BLANK_RECORD
    built_up = {
        "form": "built_up",
        "components": [
            {"id": "strap", "form": "profiled_blank", "blank": BLANK_RECORD},
            {"id": "tab", "form": "flat_bar", "section_mm": [4.0, 6.0], "length_mm": 10.0},
        ],
    }
    Plan.model_validate(_plan(built_up))
    # An explicitly unknown blank is input debt, not a contradiction.
    Plan.model_validate(_plan({"form": "profiled_blank", "blank": "unknown"}))


@pytest.mark.parametrize(
    ("stock", "message"),
    [
        ({"form": "flat_bar", "blank": BLANK_RECORD}, "so its form is 'profiled_blank'"),
        ({"blank": BLANK_RECORD}, "so its form is 'profiled_blank'"),
        (
            {"form": "profiled_blank", "blank": BLANK_RECORD, "section_mm": [4.0, 6.0]},
            "declares no section_mm",
        ),
        ({"form": "profiled_blank", "length_mm": 60.0}, "declares no length_mm"),
        ({"form": "profiled_blank", "dia_mm": 6.0}, "declares no dia_mm"),
        (
            {"form": "profiled_blank", "origin_mm": [0.0, 0.0, 0.0], "axis": [1.0, 0.0, 0.0]},
            "declares no origin_mm, axis",
        ),
        (
            {"form": "profiled_blank", "blank": {**BLANK_RECORD, "step_sha256": "ABC"}},
            "is not a lowercase SHA-256",
        ),
        (
            {"form": "profiled_blank", "blank": {**BLANK_RECORD, "profile_tolerance_mm": 0.0}},
            "profile_tolerance_mm must be positive",
        ),
        ({"form": "profiled_blank", "blank": {**BLANK_RECORD, "step": " "}}, "names no file"),
        (
            {
                "form": "profiled_blank",
                "blank": BLANK_RECORD,
                "components": [{"id": "a", "form": "round_bar"}],
            },
            "each profiled blank is a component's",
        ),
        # The form alone makes the root profiled: it cannot also be built up.
        (
            {"form": "profiled_blank", "components": [{"id": "a", "form": "round_bar"}]},
            "each profiled blank is a component's",
        ),
        (
            {
                "components": [
                    {
                        "id": "a",
                        "form": "profiled_blank",
                        "blank": BLANK_RECORD,
                        "axis": [1.0, 0.0, 0.0],
                    }
                ]
            },
            "stock.components.a is a profiled blank",
        ),
    ],
)
def test_a_contradictory_profiled_blank_is_refused(stock, message):
    with pytest.raises(ValueError, match=message):
        Plan.model_validate(_plan(stock))


def test_inventory_stock_is_never_a_profiled_blank():
    for stock in (
        {"form": "profiled_blank"},
        {"components": [{"id": "a", "blank": BLANK_RECORD, "form": "profiled_blank"}]},
    ):
        with pytest.raises(ValueError, match="is a profiled blank"):
            Inventory.model_validate({"stock": [stock]})


# --------------------------------------------------------------------------- band arithmetic


def _manifest(features, units="mm"):
    """The bundle surface band_verdict reads: the exported manifest and its definitions."""
    return SimpleNamespace(
        features={"units": units, "features": features}, feature_definitions=features
    )


def _verdict(fields, requirement, tolerance=0.127, units="mm"):
    features = {"f": {"requirements": [requirement], **fields}}
    return blank_credit.band_verdict(_manifest(features, units), "f", requirement, tolerance)


@pytest.mark.parametrize(
    ("fields", "requirement", "verdict", "margins"),
    [
        # A two-sided band wider than the cut, nominal centred: 0.373 to spare each side.
        ({"radius": [79.5, 80.5], "radius_nominal": 80.0}, "radius", "holds", (0.373, 0.373)),
        # +/-0.1 cannot hold +/-0.127 anywhere.
        ({"length": [59.9, 60.1], "length_nominal": 60.0}, "length", "exceeds", (-0.027, -0.027)),
        # One-sided +0.50/0 with the nominal on its lower limit: the cut may fall 0.127 below.
        ({"height": [8.0, 8.5], "height_nominal": 8.0}, "height", "exceeds", (-0.127, 0.373)),
        # The same band with the nominal (the blank's profile) aimed at its middle holds.
        ({"height": [8.0, 8.5], "height_nominal": 8.25}, "height", "holds", (0.123, 0.123)),
        # The nominal read the inspection way: ``nominal_<requirement>`` too.
        ({"dia": [6.0, 6.3], "nominal_dia": 6.15}, "dia", "holds", (0.023, 0.023)),
        # A nominal exactly t inside each limit is the edge of holding.
        ({"width": [3.873, 4.127], "width_nominal": 4.0}, "width", "holds", (0.0, 0.0)),
    ],
)
def test_a_length_band_must_contain_the_nominal_plus_or_minus_the_cut(
    fields, requirement, verdict, margins
):
    status, numbers = _verdict(fields, requirement)
    assert status == verdict, numbers
    assert (numbers["low_margin"], numbers["high_margin"]) == pytest.approx(margins, abs=1e-9)


def test_without_a_nominal_only_a_band_narrower_than_the_cut_is_decided():
    status, numbers = _verdict({"height": [8.0, 8.2]}, "height")
    assert (status, numbers["band_width"]) == ("exceeds", pytest.approx(0.2))
    status, numbers = _verdict({"height": [8.0, 8.5]}, "height")
    assert status == "unknown" and "nominal" in numbers["reason"]


def test_an_inch_manifest_compares_the_cut_in_inches():
    # +/-0.127 mm is +/-0.005 in exactly.
    fields = {"length": [2.0, 2.01], "length_nominal": 2.005}
    assert _verdict(fields, "length", units="in")[0] == "holds"
    fields = {"length": [2.0, 2.009], "length_nominal": 2.005}
    assert _verdict(fields, "length", units="in")[0] == "exceeds"


def test_a_position_zone_must_hold_the_x_and_y_errors_together():
    status, numbers = _verdict({"position_dia": 0.36}, "position_dia")
    assert status == "holds"
    assert numbers["needed_zone"] == pytest.approx(2 * math.sqrt(2) * 0.127)
    assert _verdict({"position_dia": 0.35}, "position_dia")[0] == "exceeds"


@pytest.mark.parametrize(
    ("fields", "verdict"),
    [
        # Equal-bilateral 0.36: 0.18 each side holds the cut's 0.1796.
        ({"surface_profile": 0.36}, "holds"),
        ({"surface_profile": 0.35}, "exceeds"),
        # The same 0.5 zone all on the material-removed side (U = 0) cannot take the
        # cut's material-added error, however wide it is.
        ({"surface_profile": 0.5, "surface_profile_u": 0.0}, "exceeds"),
        ({"surface_profile": 0.5, "surface_profile_u": 0.2}, "holds"),
        ({"surface_profile": 0.5, "surface_profile_u": "unknown"}, "unknown"),
    ],
)
def test_a_profile_zone_must_take_the_cut_on_each_side_of_its_disposition(fields, verdict):
    assert _verdict(fields, "surface_profile")[0] == verdict


def _governed(*zones):
    """``arc``'s BASIC R80, governed by each ``(owner, zone)`` profile in that order."""
    features = {"datum_a": {"datum": "A", "requirements": []}}
    features["arc"] = {"requirements": ["radius"], "radius": 80.0}
    for owner, zone in zones:
        features[owner] = {
            "requirements": ["surface_profile"],
            "surface_profile": zone,
            "surface_profile_datums": ["A"],
            "surface_profile_governs": {"arc:radius": "increases"},
        }
    return blank_credit.band_verdict(_manifest(features), "arc", "radius", 0.127)


def test_a_basic_scalar_holds_the_band_every_governing_profile_gives_it():
    status, numbers = _governed(("wide", 1.0), ("tight", 0.5))
    # Their intersection R79.75-80.25 holds 80 +/- 0.127 with 0.123 to spare.
    assert (status, numbers["band"]) == ("holds", [79.75, 80.25])
    # A looser profile can never hide a tighter one, in either order.
    for zones in ((("wide", 1.0), ("tight", 0.2)), (("tight", 0.2), ("wide", 1.0))):
        status, numbers = _governed(*zones)
        assert (status, numbers["band"]) == ("exceeds", [79.9, 80.1])


@pytest.mark.parametrize(
    ("fields", "requirement", "tolerance", "units"),
    [
        ({"land_angle_deg": [89.0, 91.0]}, "land_angle_deg", 0.127, "mm"),
        ({"finish_ra": 1.6}, "finish_ra", 0.127, "mm"),
        ({"coaxiality_dia": 0.5}, "coaxiality_dia", 0.127, "mm"),
        ({"length": [59.0, 61.0], "length_nominal": 60.0}, "length", "unknown", "mm"),
        ({"length": [59.0, 61.0], "length_nominal": 60.0}, "length", 0.127, "unknown"),
        ({"length": ["unknown", 61.0], "length_nominal": 60.0}, "length", 0.127, "mm"),
        ({"length": 60.0}, "length", 0.127, "mm"),
        ({}, "unknown", 0.127, "mm"),
    ],
)
def test_what_a_length_cut_tolerance_cannot_bound_stays_unknown(
    fields, requirement, tolerance, units
):
    assert _verdict(fields, requirement, tolerance, units)[0] == "unknown"


# --------------------------------------------------------------------------- inputs


def _bundle_copy(tmp_path):
    """The profiled-blank example and the shared inputs it names, under a temp examples/."""
    examples = tmp_path / "examples"
    shutil.copytree(FIXTURE, examples / "geometry" / "profiled-blank", ignore=_no_goldens)
    shutil.copy(FIXTURE.parent / "inventory.toml", examples / "geometry" / "inventory.toml")
    shutil.copy(ROOT / "examples" / "cutting-data.toml", examples / "cutting-data.toml")
    return examples / "geometry" / "profiled-blank"


def _no_goldens(directory, names):
    return ["expected"] if "expected" in names else []


def _edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def test_the_blank_step_is_read_hashed_and_recorded():
    bundle = load_bundle(FIXTURE / "plan.toml")
    assert bundle.paths["stock.blank"] == BLANK.resolve()
    assert bundle.hashes["stock.blank"] == BLANK_SHA
    assert bundle.input_records["stock.blank"] == {
        "path": "examples/geometry/profiled-blank/strap-blank.STEP",
        "sha256": BLANK_SHA,
    }
    assert kernel.stock_inputs(bundle) == {
        "shape": "profiled",
        "step_path": str(BLANK.resolve()),
        "step_sha256": BLANK_SHA,
    }


def test_a_blank_digest_mismatch_is_bad_input(tmp_path):
    folder = _bundle_copy(tmp_path)
    _edit(folder / "plan.toml", BLANK_SHA, "0" * 64)
    with pytest.raises(BadInput, match="stock.blank STEP bytes do not match its step_sha256"):
        load_bundle(folder / "plan.toml")


def test_a_blank_outside_the_bundle_is_bad_input(tmp_path):
    folder = _bundle_copy(tmp_path)
    shutil.copy(BLANK, tmp_path / "outside.STEP")
    _edit(folder / "plan.toml", 'step = "strap-blank.STEP"', 'step = "../../../../outside.STEP"')
    with pytest.raises(BadInput, match="escapes the input bundle"):
        load_bundle(folder / "plan.toml")


def test_a_profiled_blank_has_no_box_to_prepare(tmp_path):
    folder = _bundle_copy(tmp_path)
    plan = folder / "plan.toml"
    plan.write_text(
        plan.read_text(encoding="utf-8") + '\n[stock.prepared]\nsetup = "S1"\n',
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(BadInput, match="profiled stock has no box to trim"):
        load_bundle(plan)


def test_an_undeclared_blank_digest_keeps_the_supply_as_debt():
    bundle = load_bundle(FIXTURE / "plan.toml")
    bundle.plan["stock"]["blank"]["step_sha256"] = "unknown"
    assert "blank.step_sha256 undeclared" in kernel.stock_inputs(bundle)["reason"]


# --------------------------------------------------------------------------- cache identity


def test_blank_bytes_key_the_cache_and_a_stale_digest_never_reuses_it(tmp_path, monkeypatch):
    folder = _bundle_copy(tmp_path)
    bundle = load_bundle(folder / "plan.toml")
    calls = []

    def execute(executable, batch):
        calls.append(batch["jobs"])
        return {"results": [{"status": "ok"} for _ in batch["jobs"]]}

    monkeypatch.setattr(kernel, "discover_kernel", lambda: Path(sys.executable))
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(kernel, "_execute", execute)

    def rerun():
        object.__setattr__(bundle, "kernel", None)
        return kernel.run_geometry(bundle)

    rerun()
    assert len(calls) == 1
    # The vendor tolerance and citation are host-only: the same geometry is reused.
    bundle.plan["stock"]["blank"].update(profile_tolerance_mm=0.05, cite="another vendor")
    rerun()
    assert len(calls) == 1
    # The blank's absolute path is not identity: the same bytes elsewhere reuse the result.
    moved = tmp_path / "moved.STEP"
    shutil.copy(bundle.paths["stock.blank"], moved)
    bundle.paths["stock.blank"] = moved
    rerun()
    assert len(calls) == 1
    # New blank bytes under their own digest are new geometry.
    data = moved.read_bytes().replace(b"END-ISO-10303-21;", b"END-ISO-10303-21;\n", 1)
    moved.write_bytes(data)
    bundle.plan["stock"]["blank"]["step_sha256"] = hashlib.sha256(data).hexdigest()
    rerun()
    assert len(calls) == 2
    assert calls[1][0]["stock"]["step_sha256"] == hashlib.sha256(data).hexdigest()
    # Bytes changed under a stale digest are refused, never a hit on the old key.
    moved.write_bytes(data + b"\n")
    facts = rerun()
    assert len(calls) == 2
    assert facts["status"] == "unknown"
    assert "Profiled blank stock STEP bytes do not match its step_sha256" in facts["reason"]


# --------------------------------------------------------------------------- face credit


def _facts(contact, mapping=None):
    mapping = {ref: index for index, ref in enumerate(FACES)} if mapping is None else mapping
    return {
        "status": "ok",
        "faces": [{"index": index, "ref": ref} for index, ref in enumerate(FACES)],
        "mapping": mapping,
        "mapping_errors": {},
        "features": {},
        "ops": {},
        "setups": {},
        "as_is_contact": contact,
    }


def _on(*refs, supply="stock"):
    return {ref: {"contact": "on_supply", "supplies": [supply], "max_gap_mm": 0.0} for ref in refs}


def _credit_bundle(contact, as_is=FACES):
    """The example's failing plan with only its inspect op, every face listed as-is."""
    bundle = load_bundle(FIXTURE / "plan.toml")
    setup = bundle.plan["setups"][0]
    setup["ops"] = [op for op in setup["ops"] if op["do"] == "inspect"]
    bundle.plan["stock"]["as_is_faces"] = list(as_is)
    object.__setattr__(bundle, "kernel", _facts(contact))
    return bundle


def _statuses(bundle):
    return {row.subject: str(row.status) for row in blank_credit.evaluate(bundle)}


def test_only_faces_on_the_blank_and_within_their_bands_are_credited():
    off = {CHAMFER: {"contact": "off_supply", "supplies": [], "max_gap_mm": 1.25}}
    bundle = _credit_bundle({**_on(*set(FACES) - {CHAMFER}), **off})
    rows = blank_credit.credit(bundle, bundle.kernel)
    assert {ref: row["verdict"] for ref, row in rows.items()} == {
        BOTTOM_EDGE: "credited",
        CHAMFER: "off_blank",
        RIGHT_END: "band",
        ARC: "credited",
        LEFT_END: "band",
        BOTTOM: "credited",
        TOP: "credited",
    }
    assert _statuses(bundle) == {
        "bottom_edge": "pass",
        "corner_chamfer": "error",
        "end_faces": "error",
        "strap_faces": "pass",
        "top_arc": "pass",
    }
    [chamfer] = [row for row in blank_credit.evaluate(bundle) if row.subject == "corner_chamfer"]
    assert "lies 1.25 mm off the supplied blank" in chamfer.sentence
    [ends] = [row for row in blank_credit.evaluate(bundle) if row.subject == "end_faces"]
    # The supply range the tolerance permits, both excursions, and a remedy no undersize
    # blank defeats: machining allowance, then an op.
    assert (
        "end_faces length, cut to 60 ±0.127, may measure 59.873-60.127, outside its "
        "59.9-60.1 band by 0.027 below and 0.027 above"
    ) in ends.sentence
    assert "from a blank that leaves machining allowance on it" in ends.sentence
    [row] = coverage.evaluate(bundle)
    assert str(row.status) == "error"
    assert set(row.numbers["unclaimed_faces"]) == {CHAMFER, RIGHT_END, LEFT_END}
    assert set(row.numbers["as_is_withheld"]) == {CHAMFER, RIGHT_END, LEFT_END}


def test_faces_the_plan_does_not_credit_are_unclaimed_not_withheld():
    as_is = [BOTTOM_EDGE, ARC, BOTTOM, TOP]
    bundle = _credit_bundle(_on(*as_is), as_is)
    # With its cutting op removed, the faces no op claims and no as-is list names stay
    # plain coverage gaps; blank_credit judges only the faces the plan credits.
    [row] = coverage.evaluate(bundle)
    assert set(row.numbers["unclaimed_faces"]) == {CHAMFER, RIGHT_END, LEFT_END}
    assert "as_is_withheld" not in row.numbers
    assert set(_statuses(bundle).values()) == {"pass"}


@pytest.mark.parametrize(
    "edit",
    [
        {"profile_tolerance_mm": "unknown"},
        # A number nobody cites is no vendor fact.
        {"cite": "unknown"},
        {"cite": []},
        {"cite": ["  ", "unknown"]},
    ],
)
def test_an_unknown_or_uncited_vendor_tolerance_is_debt_never_credit(edit):
    bundle = _credit_bundle(_on(*FACES))
    bundle.plan["stock"]["blank"].update(edit)
    assert set(_statuses(bundle).values()) == {"unknown"}
    [row] = coverage.evaluate(bundle)
    assert str(row.status) == "unknown"


@pytest.mark.parametrize(
    ("fields", "verdict"),
    [
        # A listed value the schema leaves unknown is unresolved, never an absent check.
        ({"requirements": ["dome_height"], "dome_height": "unknown"}, "unknown"),
        ({"requirements": ["radius"], "radius": "unknown"}, "unknown"),
        ({"requirements": ["process"], "process": "ream"}, "unknown"),
        ({"requirements": ["mirror_symmetric"], "mirror_symmetric": True}, "unknown"),
        # A through profile and a location its own position zone governs add nothing.
        ({"requirements": ["thru"], "thru": True}, "credited"),
        (
            {"requirements": ["at", "position_dia"], "at": [1.0, 2.0, 0.0], "position_dia": 0.4},
            "credited",
        ),
        # An unknown true position is unresolved, however wide its zone.
        (
            {"requirements": ["at", "position_dia"], "at": "unknown", "position_dia": 0.4},
            "unknown",
        ),
        (
            {
                "requirements": ["at", "position_dia"],
                "at": [1.0, "unknown", 0.0],
                "position_dia": 0.4,
            },
            "unknown",
        ),
        # A reference dimension states no limit to hold.
        ({"requirements": ["depth_ref"], "depth_ref": 16.0}, "credited"),
    ],
)
def test_every_listed_requirement_is_judged_or_left_unresolved(fields, verdict):
    bundle = _credit_bundle(_on(*FACES))
    bundle.features["features"]["strap_faces"] = {
        "faces": [TOP, BOTTOM],
        "requirements": [],
        **fields,
    }
    assert blank_credit.credit(bundle, bundle.kernel)[TOP]["verdict"] == verdict


def test_a_profiled_form_with_an_unknown_blank_is_debt_never_bar_credit():
    # The kernel cannot build the supply, so it measures no contact either.
    bundle = _credit_bundle({})
    bundle.plan["stock"]["blank"] = "unknown"
    assert blank_credit.profiled_supplies(bundle) == {"stock": {}}
    assert set(_statuses(bundle).values()) == {"unknown"}
    [row] = coverage.evaluate(bundle)
    assert str(row.status) == "unknown"


def test_unmeasured_contact_or_unresolved_owners_leave_credit_unknown():
    bundle = _credit_bundle({})
    assert set(_statuses(bundle).values()) == {"unknown"}
    bundle = _credit_bundle(_on(*FACES))
    bundle.features["features"]["strap_faces"]["faces"] = "unknown"
    rows = blank_credit.credit(bundle, bundle.kernel)
    assert {row["verdict"] for row in rows.values()} == {"unknown", "band"}
    assert rows[ARC]["unresolved_features"] == ["strap_faces"]


def test_a_plan_without_a_profiled_blank_reports_no_credit_rows():
    bundle = load_bundle(ROOT / "examples" / "geometry" / "unclaimed-face" / "plan.toml")
    object.__setattr__(bundle, "kernel", {"status": "ok"})
    assert blank_credit.evaluate(bundle) == []
    assert blank_credit.credit(bundle, bundle.kernel) == {}


def test_a_bar_component_face_keeps_its_bar_credit():
    bundle = Bundle(
        {
            "part": "p",
            "stock": {
                "form": "built_up",
                "as_is_faces": [TOP, CHAMFER],
                "components": [
                    {"id": "strap", "form": "profiled_blank", "blank": BLANK_RECORD},
                    {"id": "tab", "form": "flat_bar"},
                ],
            },
            "setups": [],
        },
        {"units": "mm", "features": {"strap_faces": {"faces": [TOP], "requirements": []}}},
        {},
        {},
        {},
        {},
        {},
        ROOT,
    )
    facts = _facts({**_on(TOP, supply="stock.strap"), **_on(CHAMFER, supply="stock.tab")})
    rows = blank_credit.credit(bundle, facts)
    assert rows[TOP]["verdict"] == rows[CHAMFER]["verdict"] == "credited"
    assert rows[TOP]["owners"] == ["strap_faces"] and "owners" not in rows[CHAMFER]


# --------------------------------------------------------------------------- traveler


@pytest.mark.parametrize(
    ("edit", "printed"),
    [
        ({}, "vendor cut tolerance ±0.127 mm"),
        # An uncited number is no vendor fact on the bench either.
        ({"cite": "unknown"}, "? vendor cut tolerance not set or not cited"),
        ({"profile_tolerance_mm": "unknown"}, "? vendor cut tolerance not set or not cited"),
    ],
)
def test_the_stock_line_prints_only_a_cited_vendor_tolerance(edit, printed):
    bundle = load_bundle(FIXTURE / "plan.toml")
    bundle.plan["stock"]["blank"].update(edit)
    object.__setattr__(bundle, "kernel", {"status": "ok"})
    line = _Traveler(bundle, [], {}, None).stock_line(bundle.plan["stock"])
    assert line.startswith("profiled blank bought already cut to outline")
    assert printed in line
    assert "strap-blank.STEP" not in line


def test_a_profiled_component_prints_its_own_blank_size():
    bundle = load_bundle(FIXTURE / "plan.toml")
    box = {"stock.strap": [0.0, 0.0, 0.0, 60.0, 17.838, 2.5]}
    object.__setattr__(bundle, "kernel", {"status": "ok", "blank_bbox_mm": box})
    component = {"id": "strap", "form": "profiled_blank", "blank": BLANK_RECORD}
    line = _Traveler(bundle, [], {}, None).stock_line(component, "stock.strap")
    assert "60.000 × 17.838 × 2.500 overall, bought already cut to outline" in line


def test_an_unknown_blank_record_prints_its_debt():
    bundle = load_bundle(FIXTURE / "plan.toml")
    bundle.plan["stock"]["blank"] = "unknown"
    object.__setattr__(bundle, "kernel", {"status": "ok"})
    line = _Traveler(bundle, [], {}, None).stock_line(bundle.plan["stock"])
    assert line.startswith(
        "profiled blank bought already cut to outline, ? cut file not set, "
        "? vendor cut tolerance not set or not cited"
    )


# --------------------------------------------------------------------------- FreeCAD


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _profiled(path=BLANK, digest=BLANK_SHA):
    return {"shape": "profiled", "step_path": str(path), "step_sha256": digest}


def test_the_blank_step_is_the_supplied_solid_and_each_as_is_face_is_measured(engine):
    result = engine.run(engine.job(PLATE, as_is=FACES, stock=_profiled()))
    assert result["status"] == "ok", result
    # The laser-cut blank, not a box: the finished strap plus the 4 x 4 x 2.5 corner.
    assert result["stock"]["volume_mm3"] == pytest.approx(2388.199527, abs=1e-5)
    # Its own box, the traveler's receiving size: 60 long, the R80 crown 17.838 high.
    assert result["blank_bbox_mm"]["stock"] == pytest.approx(
        [0.0, 0.0, 0.0, 60.0, 17.838015, 2.5], abs=1e-5
    )
    contact = result["as_is_contact"]
    assert contact[CHAMFER]["contact"] == "off_supply"
    # Sampled, so at most the 2 mm its mid-line stands from the blank's x = 60 end and
    # y = 0 edge, and far past the 1e-3 mm as-is contact tolerance.
    assert 1.0 < contact[CHAMFER]["max_gap_mm"] <= 2.0
    for ref in set(FACES) - {CHAMFER}:
        assert contact[ref] == {"contact": "on_supply", "max_gap_mm": 0.0, "supplies": ["stock"]}


def test_a_blank_the_finished_part_overhangs_is_no_supply(engine):
    # The square-cornered solid cannot be cut from the chamfered one.
    stock = _profiled(PLATE, hashlib.sha256(PLATE.read_bytes()).hexdigest())
    result = engine.run(engine.job(BLANK, stock=stock))
    assert "outside the authored stock envelope" in result["stock"]["reason"]


def test_the_engine_refuses_blank_bytes_under_another_digest(engine):
    result = engine.run(engine.job(PLATE, as_is=FACES, stock=_profiled(digest="0" * 64)))
    assert "profiled blank STEP SHA-256 mismatch" in result["stock"]["reason"]
    assert "as_is_contact" not in result


def test_a_component_blank_and_a_bar_component_are_measured_face_by_face(engine):
    tab = {
        "shape": "box",
        "origin_mm": [100.0, 0.0, 0.0],
        "axis": [1.0, 0.0, 0.0],
        "section_axis": [0.0, 1.0, 0.0],
        "length_mm": 10.0,
        "section_mm": [5.0, 2.5],
    }
    stock = {"components": {"strap": _profiled(), "tab": tab}}
    result = engine.run(engine.job(PLATE, as_is=FACES, stock=stock))
    # A face off every supply stays uncredited instead of voiding the mixed supply.
    assert "reason" not in result["stock"], result["stock"]
    # Only the profiled component reports a blank box; the bar is sized by its section.
    assert list(result["blank_bbox_mm"]) == ["stock.strap"]
    contact = result["as_is_contact"]
    assert contact[CHAMFER]["contact"] == "off_supply"
    assert contact[TOP] == {"contact": "on_supply", "max_gap_mm": 0.0, "supplies": ["stock.strap"]}


_HALVES = r"""
import sys
import Part
from FreeCAD import Vector as V
out = sys.argv[sys.argv.index("--") + 1]
Part.makeBox(60, 40, 20).exportStep(out + "/block.step")
Part.makeBox(30, 40, 20, V(30, 0, 0)).exportStep(out + "/half.step")
Part.makeBox(1, 40, 20, V(59, 0, 0)).exportStep(out + "/sliver.step")
# The block with its -X half stepped down to z = 10.
Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(-1, -1, 10))).exportStep(
    out + "/step.step"
)
"""


@pytest.fixture(scope="module")
def halves(tmp_path_factory, freecad_kernel):
    """A 60 x 40 x 20 block and its +X half (x 30..60) as STEP files."""
    directory = tmp_path_factory.mktemp("blank-halves")
    script = directory / "author.py"
    script.write_text(_HALVES, encoding="utf-8")
    subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        timeout=300,
        check=False,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert set(paths) == {"block", "half", "sliver", "step"}
    return paths


def _halves_stock(halves, height, length=30.0, profiled="half"):
    """A bar (x 0..``length``, ``height`` tall) beside a profiled piece filling the
    block's +X end: the half (x 30..60) or the 1 mm sliver (x 59..60)."""
    bar = {
        "shape": "box",
        "origin_mm": [0.0, 0.0, 0.0],
        "axis": [1.0, 0.0, 0.0],
        "section_axis": [0.0, 1.0, 0.0],
        "length_mm": length,
        "section_mm": [40.0, height],
    }
    piece = halves[profiled]
    digest = hashlib.sha256(piece.read_bytes()).hexdigest()
    return {"components": {"bar": bar, "profiled": _profiled(piece, digest)}}


def test_a_face_spanning_adjacent_components_lies_on_the_joined_supply(engine, halves):
    # The block's top runs over both halves: on neither alone, on their union, answering
    # to both cuts.
    [top] = engine.refs(halves["block"], (0, 0, 20), (60, 40, 20))
    stock = _halves_stock(halves, 20.0)
    result = engine.run(engine.job(halves["block"], as_is=[top], stock=stock))
    assert result["as_is_contact"][top] == {
        "contact": "on_supply",
        "max_gap_mm": 0.0,
        "supplies": ["stock.bar", "stock.profiled"],
    }


def test_a_narrow_profiled_share_of_a_face_still_carries_it(engine, halves):
    # A 1 mm profiled sliver under the block's top beside a 59 mm bar: its 40 mm^2 share
    # is exact area, never missed between samples, so its cut answers for the top too.
    [top] = engine.refs(halves["block"], (0, 0, 20), (60, 40, 20))
    stock = _halves_stock(halves, 20.0, length=59.0, profiled="sliver")
    result = engine.run(engine.job(halves["block"], as_is=[top], stock=stock))
    assert result["as_is_contact"][top]["supplies"] == ["stock.bar", "stock.profiled"]


def test_a_neighbour_meeting_a_face_only_along_its_edge_does_not_carry_it(engine, halves):
    # The stepped block's z = 10 land is the 10 mm bar's top; the profiled half only
    # meets it along x = 30, so the land answers to the bar alone.
    [land] = engine.refs(halves["step"], (0, 0, 10), (30, 40, 10))
    stock = _halves_stock(halves, 10.0)
    result = engine.run(engine.job(halves["step"], as_is=[land], stock=stock))
    assert result["as_is_contact"][land] == {
        "contact": "on_supply",
        "max_gap_mm": 0.0,
        "supplies": ["stock.bar"],
    }


def test_the_profiled_example_needs_no_outline_ops_but_machines_the_tight_ends(freecad_kernel):
    failing = load_bundle(FIXTURE / "plan.toml")
    facts = kernel.run_geometry(failing)
    assert facts["status"] == "ok", facts
    assert facts["setups"]["S1"].get("stock_reason") is None
    [row] = coverage.evaluate(failing)
    assert str(row.status) == "error"
    assert set(row.numbers["unclaimed_faces"]) == {LEFT_END, RIGHT_END}
    assert _statuses(failing) == {
        "bottom_edge": "pass",
        "end_faces": "error",
        "strap_faces": "pass",
        "top_arc": "pass",
    }
    passing = load_bundle(FIXTURE / "machined-ends.toml")
    kernel.run_geometry(passing)
    [row] = coverage.evaluate(passing)
    assert str(row.status) == "pass", row.sentence
    assert set(_statuses(passing).values()) == {"pass"}
