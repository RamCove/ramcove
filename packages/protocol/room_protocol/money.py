"""Exact token arithmetic. 1 TAO = 10**9 rao. Never use binary floating point for money."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

RAO_PER_TAO = 10**9


def tao_to_rao(tao: str | Decimal) -> int:
    d = Decimal(tao)
    rao = d * RAO_PER_TAO
    if rao != rao.to_integral_value():
        raise ValueError(f"{tao} TAO is not an integer number of rao")
    return int(rao)


def format_tao(rao: int, places: int = 4) -> str:
    """Human display only. ``format_tao(120_000_000) == '0.1200'``."""
    if not isinstance(rao, int):
        raise TypeError("rao must be int")
    sign = "-" if rao < 0 else ""
    whole, frac = divmod(abs(rao), RAO_PER_TAO)
    frac_s = f"{frac:09d}"[:places]
    return f"{sign}{whole}.{frac_s}" if places else f"{sign}{whole}"


def round_up_rao(rao_exact: Decimal, step_rao: int) -> int:
    """Round a non-negative exact rao amount up to a multiple of ``step_rao``."""
    if rao_exact < 0 or step_rao <= 0:
        raise ValueError("amount must be >= 0 and step > 0")
    steps = (rao_exact / Decimal(step_rao)).to_integral_value(rounding=ROUND_CEILING)
    return int(steps) * step_rao
