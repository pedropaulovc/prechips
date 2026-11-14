"""Declared-input checks: enforcement names and the plan fields each one owns."""

from dataclasses import dataclass
from importlib import import_module


class CheckError(ValueError):
    """Declared plan or shop data is missing, unusable or outside a limit."""


@dataclass(frozen=True)
class Check:
    """One enforcement key; ``module`` exposes ``check(plan: LoadedPlan) -> None``.

    The named fields are accepted by the plan reader and keep exact numbers from
    whole-field bindings. Their contents are validated by the owning check. A
    check that ``reads_turning_config`` also receives the active turning config
    path (``None`` for the packaged defaults).
    """

    module: str
    tool_fields: frozenset[str] = frozenset()
    setup_fields: frozenset[str] = frozenset()
    operation_fields: frozenset[str] = frozenset()
    reads_turning_config: bool = False


# Enforced by both built-in profiles, in this order, after stock fit and turning.
CHECKS: dict[str, Check] = {
    "cutting_speeds": Check(
        module="prechips.speeds",
        operation_fields=frozenset({"speed_kind", "cut_diameter_mm"}),
    ),
    "tool_sizing": Check(
        module="prechips.sizing",
        tool_fields=frozenset({"diameter_mm", "tap_drill_mm"}),
        operation_fields=frozenset({"sizing"}),
    ),
    "indexing": Check(module="prechips.indexing", setup_fields=frozenset({"indexing"})),
    "gauge_capability": Check(
        module="prechips.gauges",
        setup_fields=frozenset({"gauge_checks"}),
        operation_fields=frozenset({"gauge_checks"}),
    ),
    "lathe_holding": Check(
        module="prechips.lathe", setup_fields=frozenset({"lathe_hold"})
    ),
    "vise_holding": Check(
        module="prechips.vise", setup_fields=frozenset({"vise_hold"})
    ),
    "milling_deflection": Check(
        module="prechips.milling",
        setup_fields=frozenset({"beam"}),
        operation_fields=frozenset({"beam", "milling_cuts"}),
        reads_turning_config=True,
    ),
    "machine_capacity": Check(
        module="prechips.capacity", setup_fields=frozenset({"envelope"})
    ),
}


def fields(kind: str) -> frozenset[str]:
    """Plan fields of one kind (tool, setup or operation) owned by any check."""
    return frozenset().union(
        *(getattr(check, f"{kind}_fields") for check in CHECKS.values())
    )


def run(name: str, plan, turning_config=None) -> None:
    """Run one check; a refusal names the check and its explicit opt-out."""
    check = CHECKS[name]
    module = import_module(check.module)
    try:
        if check.reads_turning_config:
            module.check(plan, turning_config)
        else:
            module.check(plan)
    except CheckError as error:
        raise CheckError(
            f"{name}: {error}. Use --disable-check {name} or a custom profile "
            "to opt out."
        ) from error
