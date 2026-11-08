"""The assembled rocker maps both strap sides and prepares them on the strap branch."""

from pathlib import Path

import pytest

from prechips.inputs import load_bundle
from prechips.kernel import run_geometry

ROOT = Path(__file__).resolve().parents[1]


def test_rocker_strap_faces_are_prepared_on_the_strap_before_pressing():
    bundle = load_bundle(ROOT / "examples/rocker-arm/plan.toml")
    assert bundle.plan["construction"] == "built_up"
    assert bundle.plan["stock"]["form"] == "built_up"
    setups = bundle.plan["setups"]
    (press,) = [
        setup for setup in setups if setup.get("joint", {}).get("method") == "press"
    ]
    joint = press["joint"]
    assert joint["kind"] == "cylindrical"
    socket = bundle.plan["joint_features"][joint["socket"]]
    spigot = bundle.plan["joint_features"][joint["spigot"]]
    components = {item["id"]: item for item in bundle.plan["stock"]["components"]}
    strap, hub = socket["component"], spigot["component"]
    assert strap != hub
    assert components[strap]["form"] == "flat_bar"
    assert components[hub]["form"] == "round_bar"
    owners = {f"stock.{name}": {name} for name in components}
    prepared = set()
    strap_faces = {"strap_datum_b", "strap_faces"}
    for setup in setups:
        sources = setup["stock_in"]
        sources = [sources] if isinstance(sources, str) else sources
        material = set().union(*(owners[source] for source in sources))
        owners[setup["id"]] = material
        if setup is press:
            assert material == {strap, hub}
            break
        for op in setup.get("ops", []):
            feature = op.get("feature")
            if not isinstance(feature, str) or feature not in strap_faces:
                continue
            if op["do"] not in {"face", "rough_face", "finish_face"}:
                continue
            assert material == {strap}, (setup["id"], op["op"], material)
            exported = set(bundle.feature_definitions[feature]["faces"])
            claimed = set(op.get("faces", exported))
            assert claimed and claimed <= exported
            prepared.add(feature)
    assert prepared == strap_faces


def test_rocker_export_maps_the_two_strap_sides_at_the_component_thickness(
    monkeypatch, freecad_kernel
):
    monkeypatch.setenv("FREECAD_CMD", freecad_kernel)
    bundle = load_bundle(ROOT / "examples/rocker-arm/plan.toml")
    features = bundle.feature_definitions
    strap = features["strap_faces"]
    assert strap["thickness_nominal"] == pytest.approx(2.4892)
    planes = {
        "strap_datum_b": features["strap_datum_b"]["plane"]["value"],
        "strap_faces": strap["lower_z"],
    }
    assert planes["strap_datum_b"] == pytest.approx(strap["thickness_nominal"] / 2)
    assert planes["strap_faces"] == pytest.approx(-strap["thickness_nominal"] / 2)
    # Check the authoritative finished assembly, not a successful cut on an unresolved
    # fixture. The actual route's strap-only preparation is checked separately above.
    bundle.plan["setups"] = []
    facts = run_geometry(bundle)
    assert facts["status"] == "ok"
    for name, z in planes.items():
        refs = features[name]["faces"]
        assert refs
        for ref in refs:
            assert ref not in facts["mapping_errors"]
            face = facts["faces"][facts["mapping"][ref]]
            assert face["kind"] == "Plane"
            assert [face["bbox_mm"][2], face["bbox_mm"][5]] == pytest.approx([z, z])
