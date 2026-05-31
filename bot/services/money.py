from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Currency code -> display symbol.
_SYMBOLS = {"KZT": "₸", "USD": "$", "EUR": "€", "RUB": "₽"}

_NBSP = " "  # non-breaking space — keeps the amount on one line


def format_money(amount: Decimal, currency: str = "KZT") -> str:
    """Format an amount as finance: grouped thousands, 2 decimals, currency.

    Example: format_money(Decimal("26965"), "KZT") -> "26 965,00 ₸".
    Uses a space (NBSP) as the thousands separator and a comma as the decimal
    separator, per KZ/RU convention.
    """
    quantized = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    grouped = f"{quantized:,.2f}".replace(",", _NBSP).replace(".", ",")
    symbol = _SYMBOLS.get(currency.upper(), currency.upper())
    return f"{grouped}{_NBSP}{symbol}"
