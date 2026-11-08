"""Check placement of a part-off at a plan process end face's ``to_z`` (#292).

The parted end is stock preparation a later setup faces to length. For an explicit
positive stop diameter this rule checks placement only: it does not prove a complete
face, separation or release of the exposed piece. Only part-offs onto a process
``end_face`` get a row; one that names a finished drawing face is judged by the face
rules as before.
"""

from prechips.findings import Finding
from prechips.process_features import label, parting_plane, parts_off
from prechips.rules.resolution import UNKNOWN, number, operations

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
        endpoint = op.get("to_dia")
        if plane["status"] == "pass" and number(endpoint) and endpoint > 0:
            numbers.update(to_dia=endpoint, separation=UNKNOWN)
            cite.append(f"plan.setups.{setup['id']}.ops.{op['op']}.to_dia")
            sentence = (
                f"{subject}: part_off is placed at {label(name)}, setup Z {op['to_z']:g}, "
                f"and stops at diameter {endpoint:g}; separation and retained-piece release "
                "are not established by this placement check."
            )
        elif plane["status"] == "pass":
            sentence = (
                f"{subject}: part_off leaves {label(name)} at setup Z {op['to_z']:g}, keeping "
                "the piece toward the exposed end; the remainder stays in the chuck."
            )
        else:
            sentence = f"{subject}: {label(name)}: " + "; ".join(plane["reasons"]) + "."
        findings.append(Finding(RULE, subject, plane["status"], numbers, cite, sentence))
    return findings
