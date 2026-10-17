"""A part-off prepares a plan process ``end_face`` (#292).

The pivot shaft's S0 faces its plain end (``plain_end``) on the lathe in frame T0, whose
setup +Z is model -Z. Each test turns that facing op into a part-off and perturbs the end
face or the op, then reads the ``parting_face`` row and the part-off's kernel input.
"""

import pytest
from test_cli import copy_examples
from test_process_features import set_process_key
from test_process_route import evaluate, rewrite

from prechips.inputs import load_bundle
from prechips.kernel import build_job
from prechips.process_features import process_operation

OP = ("op", "S0", 10)
# The plain end's inward normal for a part-off: into the piece toward the exposed end.
KEPT = "[0.0, 0.0, -1.0]"


def parted(tmp_path, axis=KEPT, to_z=None, do='"part_off"'):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    rewrite(plan, OP, "do", do)
    if to_z is not None:
        rewrite(plan, OP, "to_z", to_z)
    set_process_key(plan, "plain_end", "axis", axis)
    return plan


def row(plan):
    return evaluate("parting_face", load_bundle(plan)).get("S0:10")


def kernel_cut(plan):
    job = build_job(load_bundle(plan))
    setup = next(setup for setup in job["setups"] if setup["id"] == "S0")
    return next(op for op in setup["ops"] if op["subject"] == "S0:10")["process_cut"]


def test_a_part_off_at_the_end_face_plane_keeping_the_exposed_end_passes(tmp_path):
    plan = parted(tmp_path)
    found = row(plan)
    assert found.status == "pass", found.sentence
    assert found.numbers["face_z"] == pytest.approx(0.0)
    assert "keeping the piece toward the exposed end" in found.sentence
    cut = kernel_cut(plan)
    assert cut["action"] == "part_off" and "reason" not in cut


@pytest.mark.parametrize(
    ("axis", "to_z", "words"),
    [
        # The facing op's own axis: into the chuck side, the bar the part-off leaves behind.
        ("[0.0, 0.0, 1.0]", None, "its axis points toward the chuck (setup -Z)"),
        ("[1.0, 0.0, 0.0]", None, "its axis is not along setup Z"),
        (KEPT, "-0.5", "it lies at setup Z 0, not on the to_z -0.5 the blade parts at"),
    ],
)
def test_a_part_off_contradicting_its_end_face_is_an_error_and_is_not_cut(
    tmp_path, axis, to_z, words
):
    plan = parted(tmp_path, axis=axis, to_z=to_z)
    found = row(plan)
    assert found.status == "error"
    assert words in found.sentence, found.sentence
    assert words in kernel_cut(plan)["reason"]


@pytest.mark.parametrize(
    ("axis", "to_z", "words"),
    [
        ('"unknown"', None, "its at or axis is unknown"),
        (KEPT, '"unknown"', "the op's to_z is unknown"),
    ],
)
def test_an_unknown_end_face_axis_or_to_z_leaves_the_part_off_unknown(tmp_path, axis, to_z, words):
    plan = parted(tmp_path, axis=axis, to_z=to_z)
    found = row(plan)
    assert found.status == "unknown"
    assert words in found.sentence, found.sentence
    assert "reason" in kernel_cut(plan)


def test_cut_to_fit_still_cannot_make_an_end_face(tmp_path):
    # A cut-to-fit keeps the chuck side and drops the free end: never a process face.
    plan = parted(tmp_path, do='"cut_to_fit"')
    bundle = load_bundle(plan)
    op = next(op for setup in bundle.plan["setups"] for op in setup["ops"] if setup["id"] == "S0")
    reason = process_operation(bundle, op)["reason"]
    assert reason.endswith("not cut_to_fit") and "part_off" in reason
    assert row(plan) is None


def test_facing_and_finished_face_part_offs_have_no_parting_face_row(tmp_path):
    examples = copy_examples(tmp_path)
    for plan in (
        examples / "pivot-shaft" / "plan.toml",
        examples / "cone-pivot-post" / "built-up.toml",
    ):
        assert evaluate("parting_face", load_bundle(plan)) == {}
