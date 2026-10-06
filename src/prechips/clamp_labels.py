"""One label per ``hold.clamps`` entry, shared by the traveler text and the setup picture.

Every entry keeps its declared 1-based index; the prefix names its role, so a locator
or a passive support is never counted as a clamp and the text and badges agree:

- ``restraint = "locate"``: ``LOC{i}`` (positions the part, never tightened);
- ``restraint = "none"``: ``SUP{i}`` (passive support);
- ``restraint = "press"``: ``C{i}``;
- no ``restraint``: ``C{i}`` when ``clamp_order`` is absent or lists ``i``, else ``SUP{i}``.

Gaps are kept (``C1, LOC2, C3``): the number is the entry's place in the plan.
"""

from __future__ import annotations

_PREFIX = {"locate": "LOC", "none": "SUP", "press": "C"}


def clamp_labels(hold) -> list[str]:
    """Labels aligned with ``hold["clamps"]`` (an empty list when none are declared)."""
    hold = hold if isinstance(hold, dict) else {}
    clamps = hold.get("clamps")
    order = hold.get("clamp_order")
    order = order if isinstance(order, list) else None
    labels = []
    for index, clamp in enumerate(clamps if isinstance(clamps, list) else [], 1):
        restraint = clamp.get("restraint") if isinstance(clamp, dict) else None
        prefix = _PREFIX.get(restraint)
        if prefix is None:
            prefix = "C" if order is None or index in order else "SUP"
        labels.append(f"{prefix}{index}")
    return labels
