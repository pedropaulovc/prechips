"""Compare declared stock with the adapter's per-axis stock requirement."""

from math import isclose, isfinite

from prechips.traveler import LoadedPlan

# Declared-stock unit: (millimetres per unit, name used in missing-value errors).
_UNITS = {"in": (25.4, "inches"), "mm": (1.0, "mm")}


class StockError(ValueError):
    """Declared stock does not cover the CAD adapter's stock requirement."""


def check_stock_fit(plan: LoadedPlan) -> None:
    """Require matching stock dimensions without rotation or display rounding."""
    if plan.cad is None:
        raise StockError("stock_fit: CAD is required to compare blank dimensions")
    requirement = plan.cad.stock_requirement
    if requirement is None:
        raise StockError(
            "stock_fit: this CAD adapter does not provide a stock requirement"
        )
    if requirement.unit not in _UNITS:
        raise StockError("stock_fit: unsupported CAD stock requirement")
    scale, unit_name = _UNITS[requirement.unit]
    label = requirement.label
    for axis in requirement.axes:
        declared = plan.parameters.get(axis.parameter)
        if (
            type(declared) not in (int, float)
            or not isfinite(declared)
            or declared <= 0
        ):
            raise StockError(
                f"stock_fit: {axis.name}: parameters.{axis.parameter} must declare "
                f"a finite positive size in {unit_name}; "
                f"{label} {axis.required_mm:.15g} mm"
            )
        declared_mm = declared * scale
        # Ignore only floating-point conversion noise, not display rounding.
        if declared_mm < axis.required_mm and not isclose(
            declared_mm, axis.required_mm, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise StockError(
                f"stock_fit: {axis.name}: declared {declared:.15g} {requirement.unit} "
                f"({declared_mm:.15g} mm); {label} {axis.required_mm:.15g} mm"
            )
