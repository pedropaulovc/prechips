"""Member-qualified coverage and datum ownership without native CAD execution."""

from types import SimpleNamespace

import pytest

from prechips.rules import (
    accessibility,
    coverage,
    datum_consistency,
    finish_coverage,
    geometry_common,
)

REF = "#10"


def _op(member, action="finish_face", feature="face", number=10, ref=REF):
    return {
        "op": number,
        "do": action,
        "feature": feature,
        "workpiece_faces": {member: [ref]},
    }


def _setup(name, *ops):
    return {"id": name, "stock_in": "stock", "ops": list(ops)}


def _bundle(setups, definitions=None):
    definitions = definitions or {
        "face": {"kind": "face", "faces": [REF], "finish_ra": 1.6},
    }
    return SimpleNamespace(
        plan={
            "part": "pair",
            "stock": {"as_is_faces": []},
            "workpieces": {"one": {}, "two": {}},
            "setups": setups,
        },
        features={"units": "mm", "features": definitions},
        feature_definitions=definitions,
        policy={"numbers": {"refixture_budget_mm": 0.1}},
    )


def _facts(bundle):
    return {
        "status": "ok",
        # Deliberately retain the canonical map: consumers must not borrow it.
        "mapping": {REF: 0},
        "features": {name: [0] for name in bundle.feature_definitions},
        "workpiece_mapping": {"one": {REF: 0}, "two": {REF: 1}},
        "workpiece_features": {
            member: {name: [index] for name in bundle.feature_definitions}
            for index, member in enumerate(("one", "two"))
        },
        "faces": [
            {"index": index, "ref": REF, "canonical_ref": REF, "workpiece_id": member}
            for index, member in enumerate(("one", "two"))
        ],
        "ops": {
            f"{setup['id']}:{op['op']}": {
                "claimed_indices": [0 if member == "one" else 1],
                "workpiece_faces": op["workpiece_faces"],
            }
            for setup in bundle.plan["setups"]
            for op in setup["ops"]
            for member in op["workpiece_faces"]
        },
    }


def _geometry(monkeypatch, facts):
    import prechips.kernel

    monkeypatch.setattr(prechips.kernel, "run_geometry", lambda bundle: facts)
    # Isolate direction/protection proof here; exercise the real qualified claim matcher.
    monkeypatch.setattr(geometry_common, "approach_model_reason", lambda *args: None)
    monkeypatch.setattr(geometry_common, "approach_facts", lambda *args: True)
    monkeypatch.setattr(geometry_common, "member_protection_status", lambda *args: True)
    for module in (coverage, finish_coverage):
        monkeypatch.setattr(module, "provenance", lambda *args, **kwargs: [])
        monkeypatch.setattr(module, "approach_model_reason", lambda *args: None)
        monkeypatch.setattr(module, "approach", lambda *args: "milling")
    monkeypatch.setattr(coverage.blank_credit, "credit", lambda *args, **kwargs: {})


@pytest.mark.parametrize("both", [False, True])
def test_each_registered_member_requires_its_own_cut(monkeypatch, both):
    setups = [_setup("first", _op("one"))]
    if both:
        setups.append(_setup("second", _op("two")))
    bundle = _bundle(setups)
    _geometry(monkeypatch, _facts(bundle))

    cut = coverage.evaluate(bundle)[0]
    finish = finish_coverage.evaluate(bundle)[0]
    assert cut.status == finish.status == ("pass" if both else "error")
    if not both:
        assert cut.numbers["unclaimed_indices"] == [1]
        assert cut.numbers["unclaimed_faces"] == [f"two:{REF}"]
        assert finish.numbers["uncovered_faces"] == [1]


def test_wrong_member_native_indices_never_credit_sibling(monkeypatch):
    bundle = _bundle([_setup("first", _op("one")), _setup("second", _op("two"))])
    facts = _facts(bundle)
    facts["ops"]["second:10"]["claimed_indices"] = [0]
    _geometry(monkeypatch, facts)

    assert coverage.evaluate(bundle)[0].status != "pass"
    assert finish_coverage.evaluate(bundle)[0].status != "pass"
    assert (
        geometry_common.op_claims(
            bundle, facts, bundle.plan["setups"][1], bundle.plan["setups"][1]["ops"][0]
        )[0]
        is None
    )


def test_reaming_one_member_does_not_demote_other_members_drill(monkeypatch):
    bundle = _bundle(
        [
            _setup("drill-one", _op("one", "drill")),
            _setup("drill-two", _op("two", "drill")),
            _setup("ream-two", _op("two", "ream")),
        ]
    )
    _geometry(monkeypatch, _facts(bundle))

    assert geometry_common.finishing_subjects(bundle) == {"drill-one:10", "ream-two:10"}
    assert finish_coverage.evaluate(bundle)[0].status == "pass"
    assert [setup["id"] for _, setup, _ in datum_consistency._cuts(bundle, "face", "one")] == [
        "drill-one"
    ]
    assert [setup["id"] for _, setup, _ in datum_consistency._cuts(bundle, "face", "two")] == [
        "ream-two"
    ]


@pytest.mark.parametrize("unresolved", [False, True])
def test_sibling_cannot_discharge_bounded_face_debt(monkeypatch, unresolved):
    first, second = _op("one"), _op("two")
    bundle = _bundle([_setup("first", first), _setup("second", second)])
    facts = _facts(bundle)
    if unresolved:
        facts["ops"]["second:10"]["claimed_indices"] = [0]
    _geometry(monkeypatch, facts)
    _, status, _ = accessibility._carried(bundle, facts, first, {"sample_count": 3, "indices": [0]})
    assert status == "error"


def _datum_bundle():
    definitions = {
        "datum": {"kind": "face", "faces": ["#20"], "datum": "A"},
        "face": {"kind": "face", "faces": [REF], "position_datums": ["A"], "position_dia": 0.01},
    }
    return _bundle(
        [
            _setup("one", _op("one", feature="datum", ref="#20"), _op("one", number=20)),
            _setup("two", _op("two", feature="datum", ref="#20"), _op("two", number=20)),
        ],
        definitions,
    )


def test_datum_relationships_only_compare_same_member_producers(monkeypatch):
    bundle = _datum_bundle()
    monkeypatch.setattr(datum_consistency, "operation_material_status", lambda *args, **kw: True)
    row = next(row for row in datum_consistency.evaluate(bundle) if row.subject == "face")
    assert row.status == "pass"
    assert {
        (item["workpiece_id"], item["feature_op"], item["datum_op"])
        for item in row.numbers["relationships"]
    } == {("one", "one:20", "one:10"), ("two", "two:20", "two:10")}


def test_missing_member_datum_cannot_borrow_other_members_producer(monkeypatch):
    bundle = _datum_bundle()
    bundle.plan["setups"][1]["ops"] = [bundle.plan["setups"][1]["ops"][1]]
    monkeypatch.setattr(datum_consistency, "operation_material_status", lambda *args, **kw: True)
    row = next(row for row in datum_consistency.evaluate(bundle) if row.subject == "face")
    assert row.status == "unknown"
    assert {item["workpiece_id"] for item in row.numbers["relationships"]} == {"one"}


@pytest.mark.parametrize("feature", ["face", "datum"])
@pytest.mark.parametrize("known", [False, True])
def test_unresolved_recut_survives_the_combined_datum_guard(monkeypatch, feature, known):
    bundle = _datum_bundle()
    ref = REF if feature == "face" else "#20"
    cut = {"op": 30, "do": "finish_face", "feature": feature}
    if known:
        cut["workpiece_faces"] = {"two": [ref]}
    bundle.plan["setups"][-1]["ops"].append(cut)
    # Isolate already-proved material survival; real membership and cut selection
    # must still keep an unresolved producer out of a passing relationship.
    monkeypatch.setattr(datum_consistency, "operation_material_status", lambda *args, **kw: True)
    assert [
        f"{setup['id']}:{op['op']}" for _, setup, op in datum_consistency._cuts(bundle, feature)
    ] == (["one:20", "two:20", "two:30"] if feature == "face" else ["one:10", "two:10", "two:30"])
    row = next(row for row in datum_consistency.evaluate(bundle) if row.subject == "face")
    assert row.status == ("pass" if known else "unknown")


def test_unresolved_ream_does_not_demote_known_member_pilots():
    bundle = _bundle(
        [
            _setup("one", _op("one", "drill")),
            _setup("two", _op("two", "drill")),
            _setup("ambiguous", {"op": 10, "do": "ream", "feature": "face"}),
        ]
    )
    assert [setup["id"] for _, setup, _ in datum_consistency._cuts(bundle, "face")] == [
        "one",
        "two",
        "ambiguous",
    ]


def _indicated_member_bundle(*, disjoint=False):
    from prechips.kernel import workpiece_inputs

    bundle = _datum_bundle()
    datum = _setup(
        "datum",
        _op("one", feature="datum", ref="#20"),
        _op("two", feature="datum", ref="#20", number=20),
        _op("two", number=30),
    )
    source = _setup("source")
    source["stock_in"] = "datum"
    finish = _setup("finish", _op("one"))
    finish["stock_in"] = "source"
    finish["zero"] = {"transfer": {"from": "source", "indicate": ["A"]}}
    bundle.plan["setups"] = [datum, source, finish]
    bundle.plan["workpieces"] = {
        member: {
            "pose": {
                "origin": [offset, 0.0, 0.0],
                "x": [1.0, 0.0, 0.0],
                "y": [0.0, 1.0, 0.0],
                "z": [0.0, 0.0, 1.0],
                "binding": "canonical STEP target placed in batch model coordinates",
                "cite": "registered target placement",
            },
        }
        for member, offset in (("one", 0.0), ("two", 20.0))
    }
    bundle.finished_feature_owners = {"datum": "pair", "face": "pair"}
    registrations = workpiece_inputs(bundle.plan["workpieces"], bundle.features["units"])
    if disjoint:
        datum["ops"].append(
            {
                "op": 40,
                "do": "saw",
                "outputs": {
                    member: {
                        "carries_workpieces": [member],
                        "pose": bundle.plan["workpieces"][member]["pose"],
                    }
                    for member in ("one", "two")
                },
            }
        )
        source["stock_in"] = "stock_out.two"
        finish["stock_in"] = "stock_out.one"
    # Synthetic native records use the real identity/registration/path contract.
    # Live membership alone is not a containment certificate.
    bundle.kernel = {
        "status": "ok",
        "setups": {
            setup["id"]: {
                "workpieces": {
                    member: {
                        "workpiece_id": member,
                        "registration": registrations[member],
                        "partition_path": (
                            [{"split": "datum", "output": member}]
                            if disjoint and setup is not datum
                            else []
                        ),
                        "status": "pass",
                        "reasons": [],
                    }
                    for member in (
                        ("one", "two")
                        if not disjoint or setup is datum
                        else ("two",)
                        if setup is source
                        else ("one",)
                    )
                },
            }
            for setup in bundle.plan["setups"]
        },
    }
    return bundle


def test_indicated_transfer_accepts_protected_member_from_live_batch():
    from prechips.material_routes import MaterialGraph

    bundle = _indicated_member_bundle()
    assert MaterialGraph(bundle.plan).members("source") == {"one", "two"}
    assert datum_consistency.operation_members(bundle, bundle.plan["setups"][1]) is None
    row = next(row for row in datum_consistency.evaluate(bundle) if row.subject == "face")
    assert row.numbers["tolerance_mm"] < row.numbers["refixture_budget_mm"]
    assert row.status == "pass"
    relationships = {item["workpiece_id"]: item for item in row.numbers["relationships"]}
    assert set(relationships) == {"one", "two"}
    assert relationships["one"] == {
        "datum": "A",
        "datum_feature": "datum",
        "workpiece_id": "one",
        "feature_op": "finish:10",
        "datum_op": "datum:10",
        "same_setup": False,
        "indicated_transfer": True,
        "tolerance_mm": 0.01,
        "status": "pass",
    }
    assert relationships["two"]["same_setup"] is True
    assert relationships["two"]["datum_op"] == "datum:20"
    assert relationships["two"]["status"] == "pass"


@pytest.mark.parametrize(
    "invalid",
    [
        "disjoint",
        "missing_source",
        "unresolved_source",
        "missing_registration",
        "unresolved_registration",
        "missing_protection",
        "failed_protection",
        "sibling_protection",
        "stale_registration",
        "wrong_partition",
        "before_datum",
    ],
)
def test_indicated_transfer_retains_member_source_and_proof_guards(invalid):
    bundle = _indicated_member_bundle(disjoint=invalid == "disjoint")
    datum, source, finish = bundle.plan["setups"]
    proof = bundle.kernel["setups"]["source"]["workpieces"].get("one")
    if invalid == "missing_source":
        finish["zero"]["transfer"]["from"] = "absent"
    elif invalid == "unresolved_source":
        source["stock_in"] = "absent"
        finish["stock_in"] = "datum"
    elif invalid == "missing_registration":
        bundle.plan["workpieces"]["one"].pop("pose")
    elif invalid == "unresolved_registration":
        bundle.plan["workpieces"]["one"]["pose"]["binding"] = "unknown"
    elif invalid == "missing_protection":
        del bundle.kernel["setups"]["source"]["workpieces"]["one"]
    elif invalid == "failed_protection":
        proof.update(status="error", reasons=["datum target not contained in source stock"])
    elif invalid == "sibling_protection":
        proof["workpiece_id"] = "two"
    elif invalid == "stale_registration":
        proof["registration"] = bundle.kernel["setups"]["source"]["workpieces"]["two"][
            "registration"
        ]
    elif invalid == "wrong_partition":
        proof["partition_path"] = [{"split": "datum", "output": "other"}]
    elif invalid == "before_datum":
        source["stock_in"] = "stock"
        datum["stock_in"] = "source"
        finish["stock_in"] = "datum"
        bundle.plan["setups"] = [source, datum, finish]
    row = next(row for row in datum_consistency.evaluate(bundle) if row.subject == "face")
    assert row.status == "error"
    relationships = {item["workpiece_id"]: item for item in row.numbers["relationships"]}
    assert set(relationships) == {"one", "two"}
    assert relationships["one"]["indicated_transfer"] is False
    assert relationships["one"]["status"] == "error"
    assert relationships["two"]["same_setup"] is True
    assert relationships["two"]["status"] == "pass"


def test_unproved_member_datum_protection_remains_debt(monkeypatch):
    bundle = _datum_bundle()
    monkeypatch.setattr(
        datum_consistency,
        "operation_material_status",
        lambda *args, **kwargs: None if kwargs["workpiece_id"] == "two" else True,
    )
    row = next(row for row in datum_consistency.evaluate(bundle) if row.subject == "face")
    assert row.status == "unknown"


def test_explicit_face_owner_is_scoped_to_selected_member():
    bundle = _bundle([_setup("owner", _op("one", feature="other"))])
    assert len(datum_consistency._cuts(bundle, "face", "one")) == 1
    assert datum_consistency._cuts(bundle, "face", "two") == []


def test_ordinary_final_datum_cut_selection_is_unchanged():
    bundle = _bundle(
        [
            _setup("pilot", _op("one", "drill")),
            _setup("final", _op("one", "ream")),
        ]
    )
    del bundle.plan["workpieces"]
    for setup in bundle.plan["setups"]:
        for op in setup["ops"]:
            op["faces"] = op.pop("workpiece_faces")["one"]
    assert [setup["id"] for _, setup, _ in datum_consistency._cuts(bundle, "face")] == ["final"]


def test_as_stock_declaration_resolves_each_registered_face(monkeypatch):
    bundle = _bundle([])
    bundle.plan["stock"]["as_is_faces"] = [REF]
    _geometry(monkeypatch, _facts(bundle))
    row = coverage.evaluate(bundle)[0]
    assert row.status == "pass"
    assert row.numbers["claimed_face_count"] == 2


@pytest.mark.parametrize(
    "second_contact, expected",
    [
        ("on_supply", "pass"),
        ("off_supply", "error"),
        (None, "unknown"),
        ("stale_registration", "unknown"),
        ("sibling_identity", "unknown"),
    ],
)
def test_profiled_as_stock_credit_requires_each_members_contact(
    monkeypatch,
    second_contact,
    expected,
):
    from prechips.kernel import workpiece_inputs

    bundle = _bundle(
        [],
        {
            "face": {"kind": "face", "faces": [REF], "requirements": []},
        },
    )
    bundle.plan["workpieces"] = {
        member: {
            "pose": {
                "origin": [offset, 0.0, 0.0],
                "x": [1.0, 0.0, 0.0],
                "y": [0.0, 1.0, 0.0],
                "z": [0.0, 0.0, 1.0],
                "binding": "canonical STEP target placed in batch model coordinates",
                "cite": "registered target placement",
            },
        }
        for member, offset in (("one", 0.0), ("two", 20.0))
    }
    registrations = workpiece_inputs(bundle.plan["workpieces"], bundle.features["units"])
    bundle.plan["stock"].update(
        form="profiled_blank",
        as_is_faces=[REF],
        blank={"profile_tolerance_mm": 0.01, "cite": "vendor profile tolerance"},
    )
    facts = _facts(bundle)
    contact = {
        "contact": "on_supply",
        "supplies": ["stock"],
        "workpiece_id": "one",
        "registration": registrations["one"],
    }
    # Even a passing canonical record cannot substitute for a member's measurement.
    facts["as_is_contact"] = {REF: contact}
    facts["workpiece_as_is_contact"] = {"one": {REF: contact}}
    if second_contact is not None:
        facts["workpiece_as_is_contact"]["two"] = {
            REF: {
                "contact": (
                    "on_supply"
                    if second_contact in {"stale_registration", "sibling_identity"}
                    else second_contact
                ),
                "supplies": ["stock"],
                "workpiece_id": "one" if second_contact == "sibling_identity" else "two",
                "registration": (
                    registrations["one"]
                    if second_contact == "stale_registration"
                    else registrations["two"]
                ),
            },
        }
    credit = coverage.blank_credit.credit
    _geometry(monkeypatch, facts)
    monkeypatch.setattr(coverage.blank_credit, "credit", credit)
    row = coverage.evaluate(bundle)[0]
    assert row.status == expected
    assert row.numbers["claimed_face_count"] == (2 if expected == "pass" else 1)


@pytest.mark.parametrize("missing_faces", [False, True])
def test_known_member_containment_error_survives_other_coverage_debt(
    monkeypatch,
    missing_faces,
):
    from prechips.kernel import workpiece_inputs

    bundle = _bundle([_setup("arriving")])
    bundle.plan["workpieces"] = {
        member: {
            "pose": {
                "origin": [offset, 0.0, 0.0],
                "x": [1.0, 0.0, 0.0],
                "y": [0.0, 1.0, 0.0],
                "z": [0.0, 0.0, 1.0],
                "binding": "canonical STEP target placed in batch model coordinates",
                "cite": "registered target placement",
            },
        }
        for member, offset in (("one", 0.0), ("two", 20.0))
    }
    registrations = workpiece_inputs(bundle.plan["workpieces"], bundle.features["units"])
    facts = _facts(bundle)
    proof = {
        "workpiece_id": "one",
        "registration": registrations["one"],
        "partition_path": [],
        "status": "error",
        "reasons": ["registered target extends beyond arriving stock"],
    }
    facts["setups"] = {"arriving": {"workpieces": {"one": proof}}}
    if missing_faces:
        facts.pop("faces")
    # The sibling has no proof: its debt must not hide this known native error.
    _geometry(monkeypatch, facts)
    rows = coverage.evaluate(bundle)
    assert rows[0].rule == "coverage"
    assert rows[0].subject == "arriving:one"
    assert rows[0].status == "error"
    assert rows[0].numbers["setup_id"] == "arriving"
    assert rows[0].numbers["workpiece_id"] == "one"
    evidence = rows[0].numbers["member_containment"]
    assert evidence["status"] == "error"
    assert evidence["setup_id"] == "arriving"
    assert evidence["workpiece_id"] == "one"
    assert evidence["proof"] == proof
    assert evidence["reasons"] == proof["reasons"]
    assert len(rows) == 2
    assert rows[1].subject == "pair"
    if missing_faces:
        assert rows[1].status == "unknown"
