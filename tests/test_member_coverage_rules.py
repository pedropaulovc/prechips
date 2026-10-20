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


def test_indicated_transfer_does_not_borrow_sibling_source(monkeypatch):
    datum_op = _op("one", feature="datum")
    finish_op = _op("one")
    setups = [_setup("datum", datum_op), _setup("sibling", _op("two")), _setup("finish", finish_op)]
    setups[-1]["zero"] = {"transfer": {"from": "sibling", "indicate": ["A"]}}
    bundle = _bundle(setups)
    monkeypatch.setattr(
        datum_consistency,
        "operation_members",
        lambda bundle, setup, op=None: ("two",) if setup["id"] == "sibling" else ("one",),
    )
    monkeypatch.setattr(datum_consistency, "operation_material_status", lambda *args, **kw: True)
    assert not datum_consistency._indicated(
        setups,
        (2, setups[2], finish_op),
        (0, setups[0], datum_op),
        "datum",
        "A",
        bundle=bundle,
        workpiece_id="one",
    )


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
