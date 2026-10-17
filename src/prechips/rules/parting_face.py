"""A part-off onto a plan process end face leaves that face at its ``to_z`` (#292).

The parted end is stock preparation a later setup faces to length: the blade parts the
disc at ``to_z``, the piece toward the exposed end (the side the end face's ``axis``
points into) is kept and the remainder stays in the chuck with the bar. Only part-offs
onto a process ``end_face`` get a row; one that names a finished drawing face is judged
by the face rules as before.
"""

from prechips.findings import Finding
from prechips.process_features import label, parting_plane, parts_off
from prechips.rules.resolution import UNKNOWN, operations

RULE = "parting_face"


def evaluate(bundle):
    findings = []
    for setup, op in operations(bundle):
        if not parts_off(bundle, op):
            continue
        subject = f"{setup['id']}:{op['op']}"
        name = op["feature"]
        plane = parting_plane(bundle, setup, op)
        numbers = {
            "feature": label(name),
            "to_z": op.get("to_z", UNKNOWN),
            "face_z": plane["face_z"],
        }
        cite = [
            f"plan.setups.{setup['id']}.ops.{op['op']}.to_z",
            f"plan.process_features.{name}.at",
            f"plan.process_features.{name}.axis",
            "docs/plan.md: process features",
        ]
        if plane["status"] == "pass":
            sentence = (
                f"{subject}: part_off leaves {label(name)} at setup Z {op['to_z']:g}, keeping "
                "the piece toward the exposed end; the remainder stays in the chuck."
            )
        else:
            sentence = f"{subject}: {label(name)}: " + "; ".join(plane["reasons"]) + "."
        findings.append(Finding(RULE, subject, plane["status"], numbers, cite, sentence))
    return findings
