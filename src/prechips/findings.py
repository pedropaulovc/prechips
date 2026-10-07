"""Deterministic findings and shop-owned readiness gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from prechips.inputs import Bundle


class Status(StrEnum):
    PASS = "pass"
    ERROR = "error"
    WARN = "warn"
    INFO = "info"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Finding:
    rule: str
    subject: str
    status: Status | str
    numbers: dict[str, Any]
    cite: list[str]
    sentence: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", Status(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "subject": self.subject,
            "status": str(self.status),
            "numbers": self.numbers,
            "cite": self.cite,
            "message": self.sentence,
        }


# Joint rules gate physical assembly, and manual_arc gates the layout and filing a
# planned hand-finished arc needs: no policy omission can waive them.
ALWAYS_REQUIRED = frozenset({"joint_fit", "joint_assembly", "manual_arc"})


def is_required(finding: Finding, policy: dict, bundle: Bundle | None = None) -> bool:
    if finding.rule in ALWAYS_REQUIRED:
        return True
    required = policy.get("required", "unknown")
    if required == "unknown":
        return True
    selector = required.get(finding.rule)
    if selector is None:
        return False
    if finding.subject == "*" and finding.numbers.get("required") == selector:
        return True
    if selector == "*":
        return True
    if isinstance(selector, list):
        return finding.subject in selector
    if selector == "setups":
        return bundle is None or finding.subject in {s["id"] for s in bundle.plan["setups"]}
    feature = finding.subject.split(":", 1)[0]
    if selector in {"holes", "toleranced_features"} and bundle is not None:
        entry = bundle.feature_definitions.get(feature, {})
        if selector == "holes":
            return entry.get("kind") in {"hole", "counterbore", "thread"}
        from prechips.model import tolerance_requirements

        return bool(tolerance_requirements(entry))
    return finding.subject == selector or feature == selector


def exit_code(findings: list[Finding], policy: dict, bundle: Bundle | None = None) -> int:
    """Bad inputs are raised before this gate; errors precede unresolved required rows."""
    if any(f.status == Status.ERROR for f in findings):
        return 2
    if any(f.numbers.get("kernel_unavailable") is True for f in findings):
        return 4
    required = policy.get("required", "unknown")
    if required == "unknown":
        return 4
    unresolved = {Status.WARN, Status.UNKNOWN, Status.UNSUPPORTED}
    if any(f.status in unresolved and is_required(f, policy, bundle) for f in findings):
        return 4
    # Calling the gate directly must not silently waive an absent required rule.
    found_rules = {f.rule for f in findings}
    if any(rule not in found_rules for rule in required):
        return 4
    return 0
