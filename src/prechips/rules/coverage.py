"""All imported faces need cutting, as-stock, checked-joint or explicit representation credit.

A joint's ``forms`` feature is credited to the joint only when the join assembles, the
kernel admits its joined corner inside the feature's own band (a sharp corner for a
``[0, r]`` radius band), and the last op naming the feature at or after the join checks
that band with a capable gauge (:func:`~prechips.rules.inspection.requirement_check`, a
limit leaf included). Without a passing check the credit is debt, never a pass; a
refused join credits nothing.

A modeled thread envelope can cover its geometry-matched cylindrical representation
only. That separately reported credit is neither helical machining nor inspection
acceptance; manual functional relationships never supply face credit.
"""

import math

from prechips.findings import Finding
from prechips.material_routes import MaterialGraph, feature_material_status, setup_lineage
from prechips.rules import blank_credit, inspection
from prechips.rules.geometry_common import (
    LATHE_APPROACH_REASON,
    ROTARY,
    approach,
    approach_model_reason,
    cutting_action,
    finite_saw_evidence,
    op_claims,
    provenance,
    rotary_debt_text,
    rotary_gap_text,
    rotary_union,
    unavailable,
)
from prechips.rules.resolution import (
    HAND_FINISH,
    HAND_THREAD,
    SAW_OPS,
    UNKNOWN,
    claim_refs,
    face_mapping,
    known_refs,
    member_protection_evidence,
    number,
    op_check_targets,
    op_feature,
    operation_members,
    operations,
    record,
    registered_workpieces,
)

CLAIM_DEBT = "cutting claims are unknown, unmapped or undecided, or as-stock refs are unknown"
# The band a joint-formed feature's joined corner is admitted against and read in.
FORMED_REQUIREMENT = "radius"


def _face_name(face):
    """Keep a member's missing surface distinguishable from its canonical siblings."""
    ref = face.get("canonical_ref", face.get("ref"))
    return f"{face['workpiece_id']}:{ref}" if face.get("workpiece_id") else ref


def _thread_representation_faces(bundle, mapping):
    """Cosmetic feature faces cannot acquire exact credit from an earlier drill."""
    indices = set()
    for feature in bundle.feature_definitions.values():
        if (
            feature.get("kind") != "threaded_hole"
            or feature.get("representation") != "thread_envelope"
        ):
            continue
        refs = feature.get("faces")
        if not known_refs(refs):
            continue
        indices.update(
            index
            for identity, index in mapping.items()
            if (identity[1] if isinstance(identity, tuple) else identity) in refs
        )
    return indices


def _downstream(plan, sid):
    """Producer descendants only; a check still needs feature-material proof."""
    return {setup["id"] for setup in plan["setups"] if sid in setup_lineage(plan, setup["id"])}


def _after_join(setup, op, sid):
    """Whether ``op`` runs once the joint ``sid`` has formed its corner: any op of a later
    setup, and in the joint's own setup an op after its first ``fit`` (the op that joins;
    a setup with none joins on entry). An inspection before the fit reads no joined
    corner."""
    if setup["id"] != sid:
        return True
    ops = setup["ops"]
    fits = [index for index, other in enumerate(ops) if other.get("do") == "fit"]
    position = next(index for index, other in enumerate(ops) if other is op)
    return not fits or position > fits[0]


def joint_formed(bundle, facts):
    """``(credited indices, debts, pending indices, rows)`` for every feature a joint
    ``forms``; ``pending`` are the faces whose credit is debt."""
    credited, debts, pending, rows = set(), [], set(), []
    mapping = record(facts.get("mapping"))
    for setup in bundle.plan["setups"]:
        joint = record(setup.get("joint"))
        sid = setup["id"]
        detail = record(record(facts.get("setups")).get(sid))
        later = _downstream(bundle.plan, sid)
        for name in joint.get("forms") or ():
            formed = record(record(detail.get("forms")).get(name))
            row = {"joint": sid, "feature": name, "kernel": formed.get("status", UNKNOWN)}
            rows.append(row)
            if detail.get("assembly_error"):
                # The refused join (joint_assembly's error) credits nothing: faces stay open.
                row["credit"] = "refused"
                continue
            refs = record(bundle.feature_definitions.get(name)).get("faces")
            faces = (
                {mapping[ref] for ref in refs if ref in mapping}
                if isinstance(refs, list)
                else set()
            )
            if formed.get("status") != "formed":
                why = formed.get("reason") or detail.get("stock_reason") or "join unresolved"
                debts.append(f"{sid} forms {name}, but its joined corner is unresolved ({why})")
                pending |= faces
                row["credit"] = UNKNOWN
                continue
            # Only an op naming the feature checks it: an unscoped entry on another
            # feature's op reads that feature, never this corner.
            checks = [
                (s, o, target)
                for s, o in operations(bundle, name)
                if s["id"] in later
                and feature_material_status(bundle.plan, s["id"], sid, name, bundle) is not False
                and _after_join(s, o, sid)
                for target in op_check_targets(bundle, s, o)
                if target["kind"] == "dimensional"
                and target["identity"]["feature_owner"] == name
                and target["identity"]["requirement"] == FORMED_REQUIREMENT
                and target["selection_status"] == "pass"
            ]
            if not checks:
                debts.append(
                    f"{sid} forms {name}, but no check after the join reads its "
                    f"{FORMED_REQUIREMENT} band"
                )
                pending |= faces
                row["credit"] = UNKNOWN
                continue
            check_setup, op, target = checks[-1]
            if feature_material_status(bundle.plan, check_setup["id"], sid, name, bundle) is None:
                debts.append(
                    f"{sid} forms {name}, but its check's material after partition is unresolved"
                )
                pending |= faces
                row["credit"] = UNKNOWN
                continue
            status, message, _ = inspection.requirement_check(
                bundle,
                name,
                FORMED_REQUIREMENT,
                op,
                setup=check_setup,
                workpiece=target["identity"]["workpiece"],
            )
            row.update(check=f"{check_setup['id']}:{op['op']}", check_status=status)
            if status != "pass":
                debts.append(
                    f"{sid} forms {name}, but its {FORMED_REQUIREMENT} check is not a pass "
                    f"({message})"
                )
                pending |= faces
                row["credit"] = UNKNOWN
                continue
            row["credit"] = "credited"
            credited.update(formed.get("indices", ()))
    return credited, debts, pending, rows


def represented_thread_envelope(bundle, facts, setup, op):
    """Native representation-only indices and their bound evidence, never cut credit."""
    from prechips.kernel import op_inputs

    name = op_feature(op)
    feature = record(bundle.feature_definitions.get(name))
    if (
        op.get("do") != "hand_tap"
        or feature.get("kind") != "threaded_hole"
        or feature.get("representation") != "thread_envelope"
    ):
        return set(), {}
    subject = f"{setup['id']}:{op['op']}"
    detail = record(record(facts.get("ops")).get(subject))
    proof = record(detail.get("represented_thread_envelope"))
    material = record(detail.get("manual_thread"))
    evidence = {
        "operation": subject,
        "feature": name,
        "status": UNKNOWN,
        "evaluation": "represented_geometry",
        "helical_geometry": "unmodeled",
        "indices": [],
        "proof": proof,
    }

    def refused(reason):
        return set(), {**evidence, "reasons": [reason]}

    request = record(op_inputs(bundle, setup, op).get("manual_thread"))
    if (
        facts.get("status") != "ok"
        or request.get("model") != "bounded_thread_envelope_v1"
        or request.get("status") != "ready"
    ):
        return refused("the current bounded thread-region request is unresolved")
    members = operation_members(bundle, setup, op)
    if registered_workpieces(bundle):
        if not members or len(members) != 1:
            return refused("the represented thread's selected workpiece is unresolved")
        member = members[0]
        protected = member_protection_evidence(bundle, setup, member, facts)
        if protected["status"] != "pass":
            return refused("the selected workpiece has no matching native protection proof")
        registration = protected["proof"]["registration"]
        path = protected["proof"]["partition_path"]
    else:
        member, registration = None, None
        paths = {
            tuple((edge.split, edge.output) for edge in atom.path)
            for atom in MaterialGraph(bundle.plan).nodes.get(setup["id"], ())
        }
        if len(paths) != 1:
            return refused("the represented thread's material partition is unresolved")
        path = [{"split": split, "output": output} for split, output in next(iter(paths))]
    evidence["workpiece_id"] = member
    evidence["registration"] = registration
    evidence["partition_path"] = path
    if request.get("feature") != name or request.get("workpiece_id") != member:
        return refused("the current thread request does not identify this feature and member")
    for row, model in (
        (material, "bounded_thread_envelope_v1"),
        (proof, "represented_thread_envelope_v1"),
    ):
        if (
            row.get("model") != model
            or row.get("status") != "pass"
            or row.get("producer") != subject
            or row.get("feature") != name
            or row.get("workpiece_id") != member
            or "registration" not in row
            or row["registration"] != registration
            or row.get("partition_path") != path
        ):
            return refused("the native thread proof is absent, stale or owned by other material")
    region = record(request.get("region"))
    diameter = request.get("diameter_mm")
    if (
        material.get("region") != region
        or material.get("diameter_mm") != diameter
        or material.get("material") != "bounded"
        or material.get("helical_geometry") != "unmodeled"
        or not number(diameter)
        or not math.isfinite(diameter)
        or diameter <= 0
        or not number(region.get("depth_mm"))
        or not math.isfinite(region["depth_mm"])
        or region["depth_mm"] <= 0
    ):
        return refused("the native bounded region does not match the current resolved thread span")
    refs = claim_refs(bundle, op, setup)
    mapping = face_mapping(bundle, facts, setup)
    mapping_errors = record(facts.get("mapping_errors"))
    indices, surfaces = proof.get("indices"), proof.get("faces")
    if (
        not known_refs(refs)
        or any(ref not in mapping for ref in refs)
        or any(
            not isinstance(mapping[ref], int) or isinstance(mapping[ref], bool) or mapping[ref] < 0
            for ref in refs
        )
        or len({mapping[ref] for ref in refs}) != len(refs)
        or any(
            ref in mapping_errors or isinstance(ref, tuple) and ref[1] in mapping_errors
            for ref in refs
        )
        or detail.get("mapping_errors")
        or not isinstance(indices, list)
        or not indices
        or any(
            not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in indices
        )
        or len(indices) != len(set(indices))
        or not isinstance(surfaces, list)
        or len(surfaces) != len(indices)
    ):
        return refused("the native represented-face inventory is incomplete")
    expected = {mapping[ref]: ref[1] if isinstance(ref, tuple) else ref for ref in refs}
    raw_inventory = facts.get("faces")
    if not isinstance(raw_inventory, list):
        return refused("the imported native face inventory is unresolved")
    inventory = {
        face.get("index"): face
        for face in raw_inventory
        if isinstance(face, dict) and isinstance(face.get("index"), int)
    }
    seen = set()
    for raw in surfaces:
        row = record(raw)
        index, radius, axis, span = (
            row.get("index"),
            row.get("radius_mm"),
            row.get("axis"),
            row.get("span_mm"),
        )
        face = record(inventory.get(index)) if isinstance(index, int) else {}
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index not in expected
            or index in seen
            or not face
            or face.get("workpiece_id") != member
            or face.get("canonical_ref", face.get("ref")) != expected[index]
            or row.get("canonical_ref") != expected[index]
            or row.get("surface") != "cylinder"
            or row.get("coaxial") != "proved"
            or row.get("within_region") != "proved"
            or not number(radius)
            or not math.isfinite(radius)
            or not 0 < radius <= diameter / 2
            or not isinstance(axis, list)
            or len(axis) != 3
            or any(not number(value) or not math.isfinite(value) for value in axis)
            or axis != region.get("axis")
            or not isinstance(span, list)
            or len(span) != 2
            or any(not number(value) or not math.isfinite(value) for value in span)
            or not 0 <= span[0] < span[1] <= region["depth_mm"]
        ):
            return refused(
                "a credited face is not this member's coaxial cylinder inside the region"
            )
        seen.add(index)
    if seen != set(indices):
        return refused("the represented-face indices do not match their complete geometry proofs")
    return seen, {**evidence, "status": "pass", "reasons": [], "indices": sorted(seen)}


def _saw_number(value):
    return number(value) and math.isfinite(value)


def _saw_binding_matches(actual, expected):
    """Bind JSON facts without accepting a boolean in place of a numeric identity."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_saw_binding_matches(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_saw_binding_matches(a, b) for a, b in zip(actual, expected, strict=True))
        )
    if number(expected):
        return _saw_number(actual) and _saw_number(expected) and actual == expected
    return type(actual) is type(expected) and actual == expected


def _saw_output_matches(output, spec, subject, path, saw):
    """Accepted named child, including the native six-decimal conservation ledger."""
    members = spec.get("carries_workpieces")
    side = spec.get("side")
    bounds, children = output.get("bbox_mm"), output.get("children_volume_mm3")
    if (
        output.get("status") != "pass"
        or output.get("side") != side
        or output.get("partition") != subject
        or output.get("partition_path") != path
        or not isinstance(members, list)
        or not members
        or any(not isinstance(member, str) or not member for member in members)
        or len(set(members)) != len(members)
        or output.get("carries_workpieces") != members
        or output.get("whole_targets") != members
        or not isinstance(bounds, list)
        or len(bounds) != 6
        or any(not _saw_number(value) for value in bounds)
        or any(bounds[i] > bounds[i + 3] for i in range(3))
        or not isinstance(children, list)
        or len(children) != 2
        or any(not _saw_number(value) or value <= 0 for value in children)
        or any(
            not _saw_number(output.get(key)) or output[key] <= 0
            for key in ("volume_mm3", "stock_volume_before_mm3", "removed_kerf_volume_mm3")
        )
        or not _saw_number(output.get("conservation_error_mm3"))
        or not 0 <= output["conservation_error_mm3"] <= 1e-6
    ):
        return False
    index = 0 if side == "below" else 1
    # Four independently rounded volumes can differ by 2e-6 in addition to the
    # accepted native 1e-6 conservation error. This never enlarges face tolerances.
    return (
        abs(output["stock_volume_before_mm3"] - output["removed_kerf_volume_mm3"] - sum(children))
        <= 3e-6 + 1e-9
        and abs(output["volume_mm3"] - children[index]) <= 2e-6 + 1e-9
        and output["stock_volume_before_mm3"] == saw["stock_volume_before_mm3"]
        and abs(output["removed_kerf_volume_mm3"] - saw["removed_kerf_volume_mm3"]) <= 1e-6 + 1e-9
        and all(
            abs(volume - child["volume_mm3"]) <= 1e-6 + 1e-9
            for volume, child in zip(children, saw["outputs"], strict=False)
        )
    )


def _saw_face_geometry_matches(row, saw, side):
    """Complete trimmed-footprint creation witnesses, not plane coincidence alone."""
    keys = (
        "plane_z_mm",
        "plane_error_mm",
        "area_mm2",
        "area_tolerance_mm2",
        "volume_tolerance_mm3",
        "boundary_uncovered_area_mm2",
        "preexisting_boundary_area_mm2",
        "outward_column_volume_mm3",
        "outward_missing_before_mm3",
        "outward_missing_removed_mm3",
        "inward_column_volume_mm3",
        "inward_missing_child_mm3",
    )
    if any(not _saw_number(row.get(key)) for key in keys):
        return False
    band, normal = saw["cutting_band_mm"], row.get("normal")
    sign = 1 if side == "below" else -1
    edge = band[0] if side == "below" else band[1]
    width, area = band[1] - band[0], row["area_mm2"]
    area_limit = max(1e-6, area * 1e-6)
    volume_limit = max(1e-6, area * width * 1e-6)
    return (
        row.get("surface") == "plane"
        and _saw_binding_matches(normal, [0, 0, sign])
        and _saw_binding_matches(row.get("cutting_band_mm"), band)
        and area > 0
        and row["area_tolerance_mm2"] == area_limit
        and row["volume_tolerance_mm3"] == volume_limit
        and 0 <= row["plane_error_mm"] <= 1e-6
        and abs(row["plane_z_mm"] - edge) <= 1e-6
        and all(
            0 <= row[key] <= area_limit
            for key in ("boundary_uncovered_area_mm2", "preexisting_boundary_area_mm2")
        )
        and all(
            0 <= row[key] <= volume_limit
            for key in (
                "outward_missing_before_mm3",
                "outward_missing_removed_mm3",
                "inward_missing_child_mm3",
            )
        )
        and row["outward_column_volume_mm3"] > 0
        and row["inward_column_volume_mm3"] > 0
        and math.isclose(row["outward_column_volume_mm3"], area * width, rel_tol=1e-9, abs_tol=1e-9)
        and math.isclose(
            row["inward_column_volume_mm3"],
            area * min(width, 1e-3),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    )


def saw_face_credit(bundle, facts, setup, op):
    """Only a bound registered finite slitting-saw cut_off proves a newly created face."""
    from prechips.kernel import op_inputs, workpiece_inputs

    if (
        op.get("do") != "cut_off"
        or not registered_workpieces(bundle)
        or "workpiece_faces" not in op
    ):
        return set(), {}
    inputs = op_inputs(bundle, setup, op)
    if inputs.get("saw_tool") != "slitting_saw":
        return set(), {}
    subject = f"{setup['id']}:{op['op']}"
    detail = record(record(facts.get("ops")).get(subject))
    proof = record(detail.get("saw_face_credit"))
    evidence = {
        "operation": subject,
        "status": UNKNOWN,
        "indices": [],
        "faces": [],
        "proof": proof,
    }

    def refused(reason):
        native = proof.get("reasons")
        reasons = [reason] + (
            [text for text in native if isinstance(text, str) and text.strip()]
            if isinstance(native, list)
            else []
        )
        return set(), {**evidence, "reasons": list(dict.fromkeys(reasons))}

    request = {
        key: inputs[key]
        for key in (
            "subject",
            "do",
            "saw_tool",
            "kerf_mm",
            "cut_plane",
            "mounted_saw",
            "workpiece_faces",
            "outputs",
        )
        if key in inputs
    }
    geometry, _, saw = finite_saw_evidence(detail, "geometry")
    plane = record(request.get("cut_plane"))
    kerf = request.get("kerf_mm")
    if (
        facts.get("status") != "ok"
        or request.get("subject") != subject
        or request.get("do") != op.get("do")
        or record(request.get("mounted_saw")).get("model") != "finite_disk_v1"
        or geometry != "pass"
        or plane.get("axis") != "z"
        or not _saw_number(plane.get("value"))
        or not _saw_number(kerf)
        or kerf <= 0
        or proof.get("model") != "finite_saw_face_credit_v1"
        or proof.get("producer") != subject
        or proof.get("reasons", []) != []
        or not _saw_binding_matches(proof.get("request"), request)
        or not _saw_binding_matches(request.get("workpiece_faces"), op["workpiece_faces"])
        or any(
            abs(actual - expected) > 1e-6
            for actual, expected in zip(
                saw.get("cutting_band_mm", []),
                [plane["value"] - kerf / 2, plane["value"] + kerf / 2],
                strict=False,
            )
        )
    ):
        return refused("the current finite slitting-saw request and native geometry are not bound")
    members, refs = operation_members(bundle, setup, op), claim_refs(bundle, op, setup)
    mapping = face_mapping(bundle, facts, setup)
    invalid = record(facts.get("mapping_errors"))
    if (
        not members
        or not known_refs(refs)
        or len(set(refs)) != len(refs)
        or any(ref not in mapping for ref in refs)
        or any(
            not isinstance(mapping[ref], int) or isinstance(mapping[ref], bool) or mapping[ref] < 0
            for ref in refs
        )
        or len({mapping[ref] for ref in refs}) != len(refs)
        or any(ref in invalid or ref[1] in invalid for ref in refs)
        or detail.get("mapping_errors")
    ):
        return refused("the explicit member-qualified face inventory is unresolved")
    protected = {
        member: member_protection_evidence(bundle, setup, member, facts) for member in members
    }
    registrations = record(
        workpiece_inputs(bundle.plan["workpieces"], bundle.features.get("units"))
    )
    if any(
        value["status"] != "pass"
        or not _saw_binding_matches(value["proof"].get("registration"), registrations.get(member))
        for member, value in protected.items()
    ):
        return refused("the selected workpiece has no matching current native protection proof")
    specs = record(request.get("outputs"))
    outputs = record(record(record(facts.get("setups")).get(setup["id"])).get("outputs"))
    if (
        len(specs) != 2
        or any(record(spec).get("side") not in ("below", "above") for spec in specs.values())
        or {record(spec).get("side") for spec in specs.values()} != {"below", "above"}
    ):
        return refused("the current saw has no pair of registered named children")
    rows, inventory = proof.get("faces"), facts.get("faces")
    if not isinstance(rows, list) or not rows or not isinstance(inventory, list):
        return refused("the native saw face-creation inventory is absent")
    expected = {mapping[ref]: ref for ref in refs}
    seen = set()
    for raw in rows:
        row = record(raw)
        index = row.get("index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index not in expected
            or index in seen
            or (row.get("workpiece_id"), row.get("canonical_ref")) != expected[index]
        ):
            return refused(
                "the native saw face inventory contains a stale, foreign or repeated index"
            )
        seen.add(index)
    accepted = set()
    for row in rows:
        index, member = row["index"], row["workpiece_id"]
        audit = {
            "index": index,
            "workpiece_id": member,
            "canonical_ref": row["canonical_ref"],
            "status": UNKNOWN,
            "reasons": [],
            "proof": row,
        }
        evidence["faces"].append(audit)
        protection = protected[member]["proof"]
        carriers = [
            name
            for name, spec in specs.items()
            if isinstance(record(spec).get("carries_workpieces"), list)
            and member in spec["carries_workpieces"]
        ]
        candidates = [
            face for face in inventory if isinstance(face, dict) and face.get("index") == index
        ]
        if (
            row.get("status") != "pass"
            or row.get("reasons") != []
            or len(candidates) != 1
            or not _saw_binding_matches(candidates[0].get("index"), index)
            or candidates[0].get("workpiece_id") != member
            or candidates[0].get("canonical_ref", candidates[0].get("ref")) != row["canonical_ref"]
            or not _saw_binding_matches(row.get("registration"), protection["registration"])
            or not _saw_binding_matches(
                row.get("input_partition_path"), protection["partition_path"]
            )
            or len(carriers) != 1
        ):
            native = row.get("reasons")
            audit["reasons"] = [
                "the native face is not bound to this explicit live member and input",
                *(
                    [text for text in native if isinstance(text, str) and text.strip()]
                    if isinstance(native, list)
                    else []
                ),
            ]
            continue
        name = carriers[0]
        spec, output = specs[name], record(outputs.get(name))
        path = protection["partition_path"] + [{"split": setup["id"], "output": name}]
        if (
            row.get("output") != name
            or row.get("side") != spec["side"]
            or not isinstance(spec.get("pose"), dict)
            or not _saw_binding_matches(row.get("output_registration"), spec["pose"])
            or not _saw_binding_matches(row.get("partition_path"), path)
            or not _saw_binding_matches(row.get("output_proof"), output)
            or not _saw_output_matches(output, spec, subject, path, saw)
        ):
            audit["reasons"] = [
                "the face has no matching accepted named output and conservation proof"
            ]
            continue
        if not _saw_face_geometry_matches(row, saw, spec["side"]):
            audit["reasons"] = [
                "the complete newly created planar face and material columns are unproved"
            ]
            continue
        accepted.add(index)
        audit["status"] = "pass"
    return accepted, {
        **evidence,
        "status": "pass" if accepted and len(accepted) == len(refs) else UNKNOWN,
        "reasons": []
        if len(accepted) == len(refs)
        else ["not every explicit saw face is certified"],
        "indices": sorted(accepted),
    }


def evaluate(bundle):
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    subject = bundle.plan["part"]
    cite = provenance(bundle, "coverage") + [
        "plan.stock.as_is_faces; union of each cutting op's direction-valid face claims"
    ]
    containment = []
    for setup in bundle.plan["setups"]:
        for member in record(bundle.plan.get("workpieces")):
            evidence = member_protection_evidence(bundle, setup, member, facts)
            if evidence["status"] != "error":
                continue
            owner = f"{setup['id']}:{member}"
            reasons = "; ".join(map(str, evidence["reasons"]))
            containment.append(
                Finding(
                    "coverage",
                    owner,
                    "error",
                    {
                        "setup_id": setup["id"],
                        "workpiece_id": member,
                        "member_containment": evidence,
                    },
                    cite + [f"kernel.setups.{setup['id']}.workpieces.{member}"],
                    f"{owner}: "
                    f"{reasons or 'registered target is not contained in arriving stock'}.",
                )
            )
    blocked = unavailable(bundle, "coverage", subject, facts, cite)
    if blocked:
        return containment + [blocked]
    faces = facts.get("faces")
    if not isinstance(faces, list) or not faces:
        return containment + [
            Finding(
                "coverage",
                subject,
                "unknown",
                {},
                cite,
                "Imported STEP face inventory is unresolved.",
            )
        ]
    all_faces = {face["index"] for face in faces}
    claimed, rotary, errors, debt = set(), set(), [], False
    unsupported = set()
    represented, represented_rows = set(), []
    saw_rows, saw_refusals = [], {}
    mapping = face_mapping(bundle, facts)
    representation_faces = _thread_representation_faces(bundle, mapping)
    for setup, op in operations(bundle):
        if op.get("do") in HAND_THREAD:
            # Retain invalid-reference errors, but discard all exact cutting claims.
            errors.extend(op_claims(bundle, facts, setup, op)[2])
            indices, evidence = represented_thread_envelope(bundle, facts, setup, op)
            represented.update(indices)
            if evidence:
                represented_rows.append(evidence)
            if not indices:
                debt = True
            # Even a successful bounded transition proves no exact helical machining.
            continue
        if op.get("do") in SAW_OPS:
            # Ordinary claims never credit a saw, including transient joint features.
            indices, evidence = saw_face_credit(bundle, facts, setup, op)
            claimed.update(indices)
            if evidence:
                saw_rows.append(evidence)
                refs = claim_refs(bundle, op, setup)
                for ref in refs if known_refs(refs) else ():
                    index = mapping.get(ref)
                    if index is None or index in indices:
                        continue
                    reasons = [
                        reason
                        for row in evidence.get("faces", ())
                        if row.get("index") == index
                        for reason in row.get("reasons", ())
                    ] or evidence.get("reasons", [])
                    cause = "; ".join(reasons) or "complete causal boundary proof is absent"
                    saw_refusals.setdefault(index, []).append(
                        f"{setup['id']}:{op['op']}: {cause}"
                    )
            continue
        if record(record(bundle.feature_definitions.get(op_feature(op))).get("joint")):
            # Transient preparation, even with an explicit face override, credits only the
            # final STEP faces the kernel certifies its accepted finishing cut leaves.
            claimed.update(op_claims(bundle, facts, setup, op)[0] or ())
            continue
        action = cutting_action(op)
        if action is False and op.get("do") not in HAND_FINISH:
            continue
        if action is None:
            debt = True
            continue
        # Unsupported lathe claims are candidates only, never direction-valid credit.
        indices, _, invalid = op_claims(bundle, facts, setup, op)
        errors.extend(invalid)
        if indices is None:
            refs = claim_refs(bundle, op, setup)
            if (
                approach_model_reason(bundle, setup, op)
                and known_refs(refs)
                and all(ref in mapping for ref in refs)
            ):
                unsupported.update(mapping[ref] for ref in refs)
            else:
                debt = True
        else:
            # A rotary claim names faces its window merely intersects: the union decides.
            (rotary if approach(bundle, setup, op) == ROTARY else claimed).update(indices)
    refs = record(bundle.plan.get("stock")).get("as_is_faces", "unknown")
    mapping, invalid = face_mapping(bundle, facts), record(facts.get("mapping_errors"))
    # A profiled blank's as-is face counts only once supplied as cut within its bands; a
    # refused one is listed in ``as_is_withheld`` (blank_credit's row prints why).
    members = bundle.plan.get("workpieces")
    member_credits = (
        {member: blank_credit.credit(bundle, facts, workpiece_id=member) for member in members}
        if isinstance(members, dict)
        else {}
    )
    credits = {} if isinstance(members, dict) else blank_credit.credit(bundle, facts)
    withheld = []
    if credits or any(member_credits.values()):
        cite.append("blank_credit: profiled-blank as-is faces on the blank and within bands")
    if isinstance(refs, list):
        # An as-stock declaration applies independently to each registered target,
        # never through the canonical single-part index map.
        if isinstance(bundle.plan.get("workpieces"), dict):
            refs = [(member, ref) for member in bundle.plan["workpieces"] for ref in refs]
        for ref in refs:
            canonical = ref[1] if isinstance(ref, tuple) else ref
            supplied = member_credits.get(ref[0], {}) if isinstance(ref, tuple) else credits
            verdict = record(supplied.get(canonical)).get("verdict", blank_credit.CREDITED)
            if canonical == "unknown":
                debt = True
            elif canonical in invalid:
                errors.append(canonical)
            elif ref not in mapping:
                debt = True
            elif verdict == blank_credit.CREDITED:
                claimed.add(mapping[ref])
            elif verdict == "unknown":
                debt = True
            else:
                withheld.append(ref)
    else:
        debt = True
    formed, formed_debts, pending, formed_rows = joint_formed(bundle, facts)
    claimed |= formed
    if formed_rows:
        cite.append(
            "plan.setups.<id>.joint.forms: joined corner admitted by the kernel and checked"
        )
    # Explicit cosmetic thread faces never acquire exact machining/as-stock credit,
    # including when the native representation proof is missing or unresolved.
    claimed -= representation_faces
    # Whole-face claims and as-stock supersede any rotary portion of the same face.
    complete, gaps, unresolved = rotary_union(facts, "cut", rotary - claimed - representation_faces)
    claimed |= complete
    if rotary:
        cite.append("kernel rotary_coverage.cut: exact union of rotary window portions per face")
    # A formed feature's faces whose credit is debt are judged by that debt, not as missing.
    unclaimed = sorted(all_faces - claimed - represented - set(gaps) - set(unresolved) - pending)
    values = {
        "face_count": len(all_faces),
        "claimed_face_count": len(all_faces & claimed),
        "unclaimed_faces": [_face_name(face) for face in faces if face["index"] in unclaimed],
        "unclaimed_indices": unclaimed,
    }
    if saw_rows:
        values["saw_face_credit"] = saw_rows
        cite.append(
            "kernel saw_face_credit: bound finite slitting-saw creation of explicit "
            "planar member faces; no finish, tolerance or execution certification"
        )
    if represented_rows:
        values["represented_thread_envelope"] = represented_rows
        values["represented_thread_envelope_indices"] = sorted(all_faces & represented)
        values["represented_thread_envelope_face_count"] = len(all_faces & represented)
        cite.append(
            "kernel represented_thread_envelope: geometry-matched cylindrical CAD "
            "representation only; helical material remains unmodeled"
        )
    if gaps:
        values["rotary_gaps"] = list(gaps.values())
    if unresolved:
        values["rotary_unresolved"] = list(unresolved.values())
    if withheld:
        values["as_is_withheld"] = withheld
    if formed_rows:
        values["joint_formed"] = formed_rows
    uncovered = set(unclaimed) | set(gaps)
    if errors:
        values["mapping_errors"] = sorted(set(errors))
        status, message = (
            "error",
            "invalid STEP face reference(s): " + ", ".join(values["mapping_errors"]),
        )
    elif debt or formed_debts and not uncovered:
        status, message = (
            "unknown",
            "; ".join(([CLAIM_DEBT] if debt else []) + formed_debts),
        )
    elif unresolved:
        status, message = (
            "unknown",
            "rotary window coverage is unresolved for "
            + "; ".join(map(rotary_debt_text, unresolved.values())),
        )
    elif uncovered and uncovered <= unsupported:
        status, message = "unsupported", LATHE_APPROACH_REASON
    elif uncovered:
        # A mixed error names only truly missing claims and gaps, not unsupported candidates.
        candidates = uncovered & unsupported
        if candidates:
            unclaimed = sorted(set(unclaimed) - unsupported)
            gaps = {index: gap for index, gap in gaps.items() if index not in unsupported}
            values.update(
                unclaimed_faces=[_face_name(face) for face in faces if face["index"] in unclaimed],
                unclaimed_indices=unclaimed,
                unsupported_faces=[
                    _face_name(face) for face in faces if face["index"] in candidates
                ],
                unsupported_indices=sorted(candidates),
            )
            values.pop("rotary_gaps", None)
            if gaps:
                values["rotary_gaps"] = list(gaps.values())
        problems = []
        if unclaimed:
            names = []
            for face in faces:
                index = face["index"]
                if index not in unclaimed:
                    continue
                name = _face_name(face) or f"imported face index {index}"
                if index in saw_refusals:
                    cause = "; ".join(dict.fromkeys(saw_refusals[index]))
                    problems.append(
                        f"finite slitting-saw face-creation proof refused for {name} ({cause})"
                    )
                else:
                    names.append(name)
            if names:
                problems.append("faces have no cutting op or as-stock claim: " + ", ".join(names))
        if gaps:
            problems.append(
                "rotary windows leave part of a claimed face uncut: "
                + "; ".join(map(rotary_gap_text, gaps.values()))
            )
        status, message = "error", "; ".join(problems)
    else:
        status = "pass"
        if represented:
            message = (
                "every imported face has cutting, as-stock, checked-joint or explicit "
                "non-helical thread-representation coverage; represented faces are not "
                "exact machined threads"
            )
        else:
            message = (
                "every imported face is claimed by a cutting op, declared as-stock or formed by "
                "a checked joint"
                if formed
                else "every imported face is claimed by a cutting op or declared as-stock"
            )
    return containment + [
        Finding("coverage", subject, status, values, cite, f"{subject}: {message}.")
    ]
