"""Coverage of faces a joint forms: credited only when joined, admitted and checked (#301).

The issue's repro: a hub pressed through a reamed strap hole leaves the "2X R0.2 MAX" root
sharp. Kernel facts are injected; the real FreeCAD admission is test_joint_forms_kernel.
"""

from types import SimpleNamespace

import pytest

import prechips.kernel
from prechips.joint_features import formed
from prechips.rules import coverage

MEASURED = {"status": "measured", "by": "test", "date": "2026-10-17", "instrument": "certificate"}
FACES = [
    {"index": 0, "ref": "#10/ADVANCED_FACE[1]/HAF_STRAP_TOP__P01", "kind": "Plane"},
    {"index": 1, "ref": "#11/ADVANCED_FACE[2]/HAF_HUB_OD__P01", "kind": "Cylinder"},
    {"index": 2, "ref": "#12/ADVANCED_FACE[3]/HAF_HUB_ROOT__P01", "kind": "Toroid"},
    {"index": 3, "ref": "#13/ADVANCED_FACE[4]/HAF_HUB_ROOT__P02", "kind": "Toroid"},
]
ROOT = [face["ref"] for face in FACES[2:]]
INSPECT = {
    "id": "F1",
    "machine": "bench",
    "stock_in": "J1",
    "ops": [
        {"op": 45, "do": "inspect", "feature": "hub_root", "checks": {"radius": "radius-gauge"}}
    ],
}


def bundle(as_is_faces=(), forms=("hub_root",), inspect=True, gauge_range=(0.2, 1.0)):
    joint = {
        "kind": "cylindrical",
        "socket": "strap_hole",
        "spigot": "hub_land",
        "fit": "interference",
        "method": "press",
    }
    if forms:
        joint["forms"] = list(forms)
    plan = {
        "part": "hub-strap",
        "construction": "built_up",
        "stock": {
            "form": "built_up",
            "as_is_faces": list(as_is_faces),
            "components": [{"id": "hub"}, {"id": "strap"}],
        },
        "setups": [
            {
                "id": "S0",
                "machine": "mill",
                "stock_in": "stock.strap",
                "ops": [{"op": 10, "do": "finish_face", "feature": "strap_top"}],
            },
            {
                "id": "H1",
                "machine": "lathe",
                "stock_in": "stock.hub",
                "ops": [{"op": 20, "do": "finish_turn", "feature": "hub_land"}],
            },
            {
                "id": "J1",
                "machine": "bench",
                "stock_in": ["S0", "H1"],
                "joint": joint,
                "ops": [{"op": 10, "do": "fit", "feature": "hub_root"}],
            },
            *([INSPECT] if inspect else []),
        ],
    }
    definitions = {
        "strap_top": {"kind": "face", "faces": [FACES[0]["ref"]]},
        "hub_od": {"kind": "boss", "faces": [FACES[1]["ref"]]},
        "hub_root": {
            "kind": "fillet",
            "faces": ROOT,
            "requirements": ["radius"],
            "radius": [0.0, 0.2],
            "corner_radius_max_design": 0.2,
            "note": "2X R0.2 MAX",
        },
        "strap_hole": {
            "kind": "cylinder_bore",
            "joint": {"id": "strap_hole", "label": "plan.joint_features.strap_hole"},
        },
        "hub_land": {
            "kind": "cylinder_spigot",
            "joint": {"id": "hub_land", "label": "plan.joint_features.hub_land"},
        },
    }
    gauge = {
        "kind": "radius_gauge",
        "verify": False,
        "range_mm": list(gauge_range),
        "resolution_mm": {"value": 0.1, "measured": dict(MEASURED)},
    }
    return SimpleNamespace(
        plan=plan,
        features={"units": "mm", "features": definitions},
        feature_definitions=definitions,
        inventory={
            "machines": {"mill": {"kind": "mill"}, "lathe": {"kind": "lathe"}},
            "gauges": {"radius-gauge": gauge},
        },
        policy={},
        cutting_data={},
    )


def facts(forms=None, **join):
    return {
        "status": "ok",
        "faces": FACES,
        "mapping": {face["ref"]: face["index"] for face in FACES},
        "ops": {
            "S0:10": {"claimed_indices": [0]},
            # The finishing spigot turn certifies the hub OD it leaves.
            "H1:20": {"approach": "turning", "certified_indices": [1]},
        },
        "setups": {
            "J1": {
                **join,
                "forms": forms
                if forms is not None
                else {"hub_root": {"status": "formed", "indices": [2, 3], "corner": "sharp"}},
            }
        },
    }


def run(monkeypatch, b, kernel_facts):
    monkeypatch.setattr(prechips.kernel, "run_geometry", lambda _bundle: kernel_facts)
    (finding,) = coverage.evaluate(b)
    return finding


def test_formed_and_limit_checked_root_passes(monkeypatch):
    finding = run(monkeypatch, bundle(), facts())
    assert finding.status == "pass", finding.sentence
    assert "formed by a checked joint" in finding.sentence
    (row,) = finding.numbers["joint_formed"]
    assert row["credit"] == "credited"
    assert row["check"] == "F1:45"


def test_formed_root_without_an_inspection_is_debt(monkeypatch):
    finding = run(monkeypatch, bundle(inspect=False), facts())
    assert finding.status == "unknown"
    assert "no check after the join reads its radius band" in finding.sentence


def test_a_check_that_cannot_read_the_limit_is_debt(monkeypatch):
    # A leaf set starting above R0.2 has no leaf at the MAX: inspection errors, no credit.
    finding = run(monkeypatch, bundle(gauge_range=(0.5, 1.0)), facts())
    assert finding.status == "unknown"
    assert "radius check is not a pass" in finding.sentence


def test_a_check_before_the_join_does_not_read_the_joined_corner(monkeypatch):
    b = bundle(inspect=False)
    b.plan["setups"][1]["ops"].append(
        {"op": 30, "do": "inspect", "feature": "hub_root", "checks": {"radius": "radius-gauge"}}
    )
    assert run(monkeypatch, b, facts()).status == "unknown"


def test_unresolved_join_is_debt(monkeypatch):
    finding = run(monkeypatch, bundle(), facts(forms={}, stock_reason="joined stock unknown"))
    assert finding.status == "unknown"
    assert "joined corner is unresolved (joined stock unknown)" in finding.sentence


def test_refused_join_credits_nothing(monkeypatch):
    finding = run(monkeypatch, bundle(), facts(forms={}, assembly_error="sharp, outside band"))
    assert finding.status == "error"
    assert finding.numbers["unclaimed_faces"] == ROOT


def test_without_forms_the_root_still_has_no_claim(monkeypatch):
    finding = run(monkeypatch, bundle(forms=()), facts(forms={}))
    assert finding.status == "error"
    assert "faces have no cutting op or as-stock claim" in finding.sentence
    assert finding.numbers["unclaimed_faces"] == ROOT


def _manifest(feature, units="mm"):
    return SimpleNamespace(features={"units": units, "features": {"root": feature}})


def test_forms_request_carries_faces_and_mm_band():
    feature = {"requirements": ["radius"], "radius": [0.0, 0.008], "faces": ROOT}
    request = formed(_manifest(feature, units="in"), "root")
    assert request["faces"] == ROOT
    assert request["radius_mm"] == pytest.approx([0.0, 0.2032])


@pytest.mark.parametrize(
    ("feature", "outcome"),
    [
        (None, "error"),
        ({"requirements": ["dia"], "dia": [1.0, 1.1], "faces": ROOT}, "error"),
        ({"requirements": ["radius"], "radius": "unknown", "faces": ROOT}, "reason"),
        ({"requirements": ["radius"], "radius": [0.0, 0.2], "faces": "unknown"}, "reason"),
        ({"requirements": ["radius"], "radius": [0.0, "unknown"], "faces": ROOT}, "reason"),
    ],
)
def test_forms_request_refuses_or_defers_what_it_cannot_admit(feature, outcome):
    b = _manifest(feature) if feature else SimpleNamespace(features={"features": {}})
    request = formed(b, "root")
    assert outcome in request
    # An undecided corner keeps its known faces: they bound what its debt can excuse.
    known = feature and feature.get("faces") == ROOT
    assert (request.get("faces") == ROOT) == bool(outcome == "reason" and known)


def _with_forms(forms):
    from test_joint_features import _plan

    return _plan().replace(
        'cite = "AUTHOR\'S CHOICE: diametral fit"',
        f'cite = "AUTHOR\'S CHOICE: diametral fit"\nforms = {forms}',
    )


def test_joint_forms_reaches_the_kernel_request(tmp_path):
    from test_joint_features import _load

    from prechips.joint_features import setup_joint

    b = _load(tmp_path, _with_forms('["subject"]'))
    joint = setup_joint(b, b.plan["setups"][2])
    # The scratch "subject" has no radius band: a declaration the kernel refuses.
    assert joint["forms"] == [{"feature": "subject", "error": formed(b, "subject")["error"]}]
    assert "no radius band" in joint["forms"][0]["error"]


@pytest.mark.parametrize("forms", ['["socket"]', '["subject", "subject"]'])
def test_joint_cannot_form_its_own_interface_or_a_feature_twice(tmp_path, forms):
    from test_joint_features import _load

    from prechips.inputs import BadInput

    with pytest.raises(BadInput):
        _load(tmp_path, _with_forms(forms))


def test_a_check_of_another_feature_does_not_credit_the_formed_corner(monkeypatch):
    # An unscoped radius check on an op naming the hub OD reads the OD, not the root.
    b = bundle()
    b.plan["setups"][3]["ops"][0]["feature"] = "hub_od"
    finding = run(monkeypatch, b, facts())
    assert finding.status == "unknown"
    assert "no check after the join reads its radius band" in finding.sentence


def test_formed_debt_does_not_hide_an_unrelated_unclaimed_face(monkeypatch):
    kernel = facts()
    kernel["ops"]["S0:10"] = {"claimed_indices": []}  # the strap top is left unclaimed
    finding = run(monkeypatch, bundle(inspect=False), kernel)
    assert finding.status == "error"
    assert finding.numbers["unclaimed_faces"] == [FACES[0]["ref"]]


def test_a_malformed_radius_band_cannot_be_formed():
    feature = {"requirements": ["radius"], "radius": [0.0, 0.1, 0.2], "faces": ROOT}
    assert "no radius band" in formed(_manifest(feature), "root")["error"]


def _sockets(edge_break, units="mm"):
    from prechips.joint_features import mouth_break

    socket = {"kind": "cylinder_bore"}
    if edge_break is not None:
        socket["edge_break"] = edge_break
    b = SimpleNamespace(plan={"joint_features": {"socket": socket}}, features={"units": units})
    return mouth_break(b, "socket")


@pytest.mark.parametrize(
    ("edge_break", "units", "expected"),
    [
        ({"kind": "sharp"}, "mm", {"kind": "sharp"}),
        ({"kind": "chamfer", "size": 0.25}, "mm", {"kind": "chamfer", "size_mm": 0.25}),
        ({"kind": "radius", "size": 0.01}, "in", {"kind": "radius", "size_mm": 0.254}),
    ],
)
def test_a_declared_mouth_break_reaches_the_kernel_in_mm(edge_break, units, expected):
    assert _sockets(edge_break, units) == pytest.approx(expected)


@pytest.mark.parametrize("edge_break", [None, {"kind": "chamfer", "size": "unknown"}])
def test_an_undeclared_or_unknown_mouth_break_is_debt(edge_break):
    assert "reason" in _sockets(edge_break)


def test_forms_sends_the_socket_mouth_break(tmp_path):
    from test_joint_features import _load

    from prechips.joint_features import setup_joint

    text = _with_forms('["subject"]').replace(
        'cite = "AUTHOR\'S CHOICE: socket preparation"',
        'cite = "AUTHOR\'S CHOICE: socket preparation"\nedge_break = { kind = "sharp" }',
    )
    b = _load(tmp_path, text)
    assert setup_joint(b, b.plan["setups"][2])["socket_break"] == {"kind": "sharp"}
    b = _load(tmp_path, _plan_without_forms())
    assert "socket_break" not in setup_joint(b, b.plan["setups"][2])


def _plan_without_forms():
    from test_joint_features import _plan

    return _plan()


@pytest.mark.parametrize(
    "edge_break",
    [
        '{ kind = "sharp", size = 0.1 }',
        '{ kind = "chamfer" }',
        '{ kind = "radius", size = 0 }',
    ],
)
def test_malformed_mouth_break_is_bad_input(tmp_path, edge_break):
    from test_joint_features import _load

    from prechips.inputs import BadInput

    text = _with_forms('["subject"]').replace(
        'cite = "AUTHOR\'S CHOICE: socket preparation"',
        f'cite = "AUTHOR\'S CHOICE: socket preparation"\nedge_break = {edge_break}',
    )
    with pytest.raises(BadInput):
        _load(tmp_path, text)


def test_a_spigot_has_no_mouth_break(tmp_path):
    from test_joint_features import _load

    from prechips.inputs import BadInput

    text = _with_forms('["subject"]').replace(
        'cite = "AUTHOR\'S CHOICE: spigot preparation"',
        'cite = "AUTHOR\'S CHOICE: spigot preparation"\nedge_break = { kind = "sharp" }',
    )
    with pytest.raises(BadInput):
        _load(tmp_path, text)


def test_an_inspection_before_the_joining_fit_does_not_read_the_formed_corner(monkeypatch):
    # In the joint's own setup the corner exists only once its first fit joins the parts.
    b = bundle(inspect=False)
    joint_setup = b.plan["setups"][2]
    check = {"op": 5, "do": "inspect", "feature": "hub_root", "checks": {"radius": "radius-gauge"}}
    joint_setup["ops"].insert(0, check)
    finding = run(monkeypatch, b, facts())
    assert finding.status == "unknown"
    assert "no check after the join" in finding.sentence
    joint_setup["ops"].append({**check, "op": 20})
    assert run(monkeypatch, b, facts()).status == "pass"
