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


class SelectorMatch(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNKNOWN = "unknown"


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


# Joint rules gate physical assembly, manual_arc gates the layout and filing a planned
# hand-finished arc needs, a centre the work rides on must be one the stock already
# has, and prepared_blank gates the size of the blank a declared preparation hands the
# first machining setup; bought tooling no receipt check can accept leaves the setup
# nothing proven to hold or guide the work with; a keep that cannot pick the piece that
# leaves a held split leaves every later setup's stock unknown: no policy omission can
# waive them. A not_applicable row never blocks.
ALWAYS_REQUIRED = frozenset(
    {
        "joint_fit",
        "joint_assembly",
        "joint_thread",
        "manual_arc",
        "centre_support",
        "tooling_hole",
        "prepared_blank",
        "purchased_tooling",
        "keep_piece",
    }
)


def _feature_owners(finding: Finding, bundle: Bundle) -> frozenset[str] | None:
    """Known owners of an inspection; unresolved ownership is not nonselection."""
    definitions = bundle.feature_definitions
    if finding.rule == "inspection" and "identity" in finding.numbers:
        identity = finding.numbers["identity"]
        if not isinstance(identity, dict) or "feature_owner" not in identity:
            return None
        owner = identity["feature_owner"]
        if isinstance(owner, str):
            return frozenset({owner}) if isinstance(definitions.get(owner), dict) else None
        if owner is not None:
            return None
        acceptance = bundle.features.get("acceptance")
        requirement = identity.get("requirement")
        relationship = (
            acceptance.get(requirement)
            if isinstance(acceptance, dict) and isinstance(requirement, str)
            else None
        )
        participants = relationship.get("features") if isinstance(relationship, dict) else None
        if (
            not isinstance(participants, list)
            or not participants
            or any(
                not isinstance(name, str) or not isinstance(definitions.get(name), dict)
                for name in participants
            )
        ):
            return None
        return frozenset(participants)
    # Legacy unqualified feature rows remain supported. Match source-owned IDs;
    # never decode a member/shared subject to infer an inspection owner.
    owners = frozenset(
        name
        for name in definitions
        if finding.subject == name or finding.subject.startswith(name + ":")
    )
    return (
        owners if owners and all(isinstance(definitions[name], dict) for name in owners) else None
    )


def selector_match(
    finding: Finding, selector: str | list[str], bundle: Bundle | None = None
) -> SelectorMatch:
    """Match policy ownership without turning missing evidence into nonselection.

    Readiness treats unknown selection conservatively; required coverage needs
    MATCH rather than crediting unresolved ownership.
    """
    if finding.subject == "*" and finding.numbers.get("required") == selector:
        return SelectorMatch.MATCH
    if selector == "*":
        return SelectorMatch.MATCH
    if isinstance(selector, list):
        return SelectorMatch.MATCH if finding.subject in selector else SelectorMatch.NO_MATCH
    if selector == "setups":
        if bundle is None:
            return SelectorMatch.UNKNOWN
        return (
            SelectorMatch.MATCH
            if any(finding.subject == setup["id"] for setup in bundle.plan["setups"])
            else SelectorMatch.NO_MATCH
        )
    if selector not in {"holes", "toleranced_features"} and finding.subject == selector:
        return SelectorMatch.MATCH
    if bundle is None:
        return SelectorMatch.UNKNOWN
    identity = finding.numbers.get("identity")
    acceptance = bundle.features.get("acceptance")
    if selector not in {"holes", "toleranced_features"}:
        relationship = isinstance(acceptance, dict) and selector in acceptance
        if selector not in bundle.feature_definitions and not relationship:
            return SelectorMatch.NO_MATCH
        owners = _feature_owners(finding, bundle)
        if owners is None:
            return SelectorMatch.UNKNOWN
        if relationship:
            if (
                finding.rule != "inspection"
                or not isinstance(identity, dict)
                or identity.get("feature_owner") is not None
            ):
                return SelectorMatch.NO_MATCH
            return (
                SelectorMatch.MATCH
                if identity.get("requirement") == selector
                else SelectorMatch.NO_MATCH
            )
        return SelectorMatch.MATCH if selector in owners else SelectorMatch.NO_MATCH
    owners = _feature_owners(finding, bundle)
    if owners is None:
        return SelectorMatch.UNKNOWN
    if selector == "holes":
        # Import after findings has initialized: rules imports Finding itself.
        from prechips.rules.resolution import HOLE_KINDS

        kinds = [bundle.feature_definitions[name].get("kind", "unknown") for name in owners]
        if any(kind in HOLE_KINDS for kind in kinds):
            return SelectorMatch.MATCH
        return SelectorMatch.UNKNOWN if "unknown" in kinds else SelectorMatch.NO_MATCH
    from prechips.model import tolerance_requirements

    return (
        SelectorMatch.MATCH
        if any(tolerance_requirements(bundle.feature_definitions[name]) for name in owners)
        else SelectorMatch.NO_MATCH
    )


def is_required(finding: Finding, policy: dict, bundle: Bundle | None = None) -> bool:
    if finding.rule in ALWAYS_REQUIRED:
        return True
    required = policy.get("required", "unknown")
    if required == "unknown":
        return True
    selector = required.get(finding.rule)
    if selector is None:
        return False
    return selector_match(finding, selector, bundle) != SelectorMatch.NO_MATCH


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
