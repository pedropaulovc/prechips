"""Independent inputs for regressions of retired manufacturing routes.

Pinned from d942578676695ebad530856b16e84e734a397d67, before the CAD-authoritative
reconciliation. These are test scenarios, not current part specifications or
shop observations. Keep current-example contract tests on ``examples/`` instead.
"""

import shutil
from pathlib import Path

HISTORICAL_EXAMPLES = Path(__file__).resolve().parent / "data" / "historical_examples"


def copy_historical_examples(tmp_path):
    """Copy retired routes, supplementing the unchanged current bracket inputs."""
    examples = Path(shutil.copytree(HISTORICAL_EXAMPLES, tmp_path / "examples"))
    # Bracket geometry is not being reconciled; avoid another copy of its input tree.
    # Preserve the historical report oracle already copied above.
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "examples" / "pivot-bracket",
        examples / "pivot-bracket",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("expected"),
    )
    return examples
