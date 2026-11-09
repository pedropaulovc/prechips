"""Compare declared per-blank dimensions with the matching CAD envelope axes."""

from math import isclose, isfinite

from prechips.traveler import LoadedPlan


class StockError(ValueError):
    """Declared stock does not cover the CAD envelope."""


def check_stock_fit(plan: LoadedPlan) -> None:
    """Require length, width and thickness without rotating or rounding stock."""
    if plan.cad is None:
        raise StockError("stock_fit: CAD is required to compare blank dimensions")
    if plan.cad.envelope_mm is None:
        raise StockError(
            "stock_fit: this CAD adapter does not provide a stock envelope"
        )
    for axis, required_mm in zip(
        ("length", "width", "thickness"), plan.cad.envelope_mm, strict=True
    ):
        key = f"blank_{axis}_in"
        declared_in = plan.parameters.get(key)
        if (
            type(declared_in) not in (int, float)
            or not isfinite(declared_in)
            or declared_in <= 0
        ):
            raise StockError(
                f"stock_fit: {axis}: parameters.{key} must declare a finite positive "
                f"size in inches; CAD requires {required_mm:.15g} mm"
            )
        declared_mm = declared_in * 25.4
        # Ignore only floating-point conversion noise, not display rounding.
        if declared_mm < required_mm and not isclose(
            declared_mm, required_mm, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise StockError(
                f"stock_fit: {axis}: declared {declared_in:.15g} in "
                f"({declared_mm:.15g} mm); CAD requires {required_mm:.15g} mm"
            )
