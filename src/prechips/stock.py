"""Compare declared stock with the adapter's rectangular or round demand."""

from math import isclose, isfinite

from prechips.cad import RectangularStock, RoundStock
from prechips.traveler import LoadedPlan


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
    if isinstance(requirement, RectangularStock):
        dimensions = (
            ("length", "blank_length_in", requirement.length_mm),
            ("width", "blank_width_in", requirement.width_mm),
            ("thickness", "blank_thickness_in", requirement.thickness_mm),
        )
        unit, scale = "in", 25.4
        unit_name = "inches"
        requirement_label = "CAD requires"
    elif isinstance(requirement, RoundStock):
        dimensions = (
            ("diameter", "stock_dia_mm", requirement.diameter_mm),
            ("length", "stock_length_mm", requirement.length_mm),
        )
        unit, scale = "mm", 1.0
        unit_name = "mm"
        requirement_label = "required"
    else:
        raise StockError("stock_fit: unsupported CAD stock requirement")
    for axis, key, required_mm in dimensions:
        declared = plan.parameters.get(key)
        if (
            type(declared) not in (int, float)
            or not isfinite(declared)
            or declared <= 0
        ):
            raise StockError(
                f"stock_fit: {axis}: parameters.{key} must declare a finite positive "
                f"size in {unit_name}; {requirement_label} {required_mm:.15g} mm"
            )
        declared_mm = declared * scale
        # Ignore only floating-point conversion noise, not display rounding.
        if declared_mm < required_mm and not isclose(
            declared_mm, required_mm, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise StockError(
                f"stock_fit: {axis}: declared {declared:.15g} {unit} "
                f"({declared_mm:.15g} mm); {requirement_label} {required_mm:.15g} mm"
            )
