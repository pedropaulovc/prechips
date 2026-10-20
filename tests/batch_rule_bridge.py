"""Pure host counterpart of test_batch_native._route; never runs native code.

The source job supplies authored registrations and routing, and the unmodified
result supplies native evidence. No MaterialGraph or rule verdict manufactures a
partition path or protection proof. This is a fixture bridge, not a production
native-to-plan importer or an alternative Plan validator.
"""

from copy import deepcopy
from pathlib import Path

from prechips.inputs import Bundle
from prechips.kernel.step_faces import StepFile


def host_bundle_from_native(job, result, refs):
    """Bind the four-instance native fixture to real source ownership and rules.

    The fixture's native job uses mm throughout. Host provenance is supplied for
    those same authored poses; shared production normalizers still perform all
    proof matching. STEP ownership comes from the exact authored source bytes,
    not a mocked finished_feature_owners property. The result is retained intact.
    """
    source_path = Path(job["step_path"])
    solids = StepFile(source_path.read_bytes().decode("latin-1")).solid_refs()
    if len(solids) != 1:
        raise ValueError("the batch bridge requires the fixture's one canonical solid")

    cite = "independently authored four-instance native route fixture"

    def pose(value):
        return {**deepcopy(value), "binding": cite, "cite": cite}

    workpieces = {
        member: {"pose": pose(instance["pose"]), "cite": cite}
        for member, instance in job["workpieces"].items()
    }
    frames = {}
    setups = []
    for authored in job["setups"]:
        sid = authored["id"]
        frame_id = f"fixture_{sid}"
        frames[frame_id] = pose(authored["frame"])
        ops = []
        for native_op in authored["ops"]:
            prefix, separator, ordinal = native_op["subject"].rpartition(":")
            if prefix != sid or not separator or not ordinal.isdecimal():
                raise ValueError("the native fixture operation must name its setup ordinal")
            op = deepcopy(native_op)
            op.pop("subject")
            op["op"] = int(ordinal)
            op["feature"] = "canonical"
            op["cite"] = cite
            for output in op.get("outputs", {}).values():
                output["pose"] = pose(output["pose"])
            ops.append(op)
        setups.append(
            {
                "id": sid,
                "stock_in": deepcopy(authored["stock_in"]),
                "frame": frame_id,
                "machine": "fixture_mill",
                "ops": ops,
                "cite": cite,
            }
        )
    return Bundle(
        plan={
            "part": "four-instance-native-bridge",
            "units": "mm",
            "workpieces": workpieces,
            "stock": {
                "form": "flat_bar",
                "length_mm": job["stock"]["length_mm"],
                "section_mm": deepcopy(job["stock"]["section_mm"]),
                "as_is_faces": list(job.get("as_is_faces", [])),
                "cite": cite,
            },
            "frames": frames,
            "setups": setups,
        },
        features={
            "units": "mm",
            "solids": {"canonical_solid": solids[0]},
            "features": {"canonical": {"kind": "profile", "faces": list(refs)}},
        },
        inventory={"machines": {"fixture_mill": {"kind": "mill"}}},
        policy={},
        cutting_data={},
        paths={"step": source_path},
        hashes={"step": job["step_sha256"]},
        root=source_path.parent,
        kernel=result,
    )
