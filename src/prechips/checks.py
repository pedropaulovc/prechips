"""Declared-input checks: enforcement names and the plan fields each one owns."""

from dataclasses import dataclass
from importlib import import_module


class CheckError(ValueError):
    """Declared plan or shop data is missing, unusable or outside a limit."""


@dataclass(frozen=True)
class Check:
    """One enforcement key; ``module`` exposes ``check(plan: LoadedPlan) -> None``.

    The named fields are accepted by the plan reader and keep exact numbers from
    whole-field bindings. Their contents are validated by the owning check.
    """

    module: str
    tool_fields: frozenset[str] = frozenset()
    setup_fields: frozenset[str] = frozenset()
    operation_fields: frozenset[str] = frozenset()


# Enforced by both built-in profiles, in this order, after stock fit and turning.
CHECKS: dict[str, Check] = {
    "cutting_speeds": Check(
        module="prechips.speeds",
        operation_fields=frozenset({"speed_kind", "cut_diameter_mm"}),
    ),
}


def fields(kind: str) -> frozenset[str]:
    """Plan fields of one kind (tool, setup or operation) owned by any check."""
    return frozenset().union(
        *(getattr(check, f"{kind}_fields") for check in CHECKS.values())
    )


def run(name: str, plan) -> None:
    """Run one check; a refusal names the check and its explicit opt-out."""
    try:
        import_module(CHECKS[name].module).check(plan)
    except CheckError as error:
        raise CheckError(
            f"{name}: {error}. Use --disable-check {name} or a custom profile "
            "to opt out."
        ) from error
