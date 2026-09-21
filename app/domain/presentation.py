"""Shared formatting. Preview, email and plain text all render through this."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Below this, a value is real but would format as "0", which reads as no change.
TINY = Decimal("0.01")


def _quantise(value: float) -> Decimal:
    return Decimal(str(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_number(value: float) -> str:
    """Up to two decimals, trailing zeros removed, negative zero normalised."""
    quantised = _quantise(value).normalize()
    if quantised == 0:
        return "0"
    text = format(quantised, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_signed(value: float) -> str:
    """Signed value; tiny nonzero changes keep their direction rather than show 0."""
    quantised = _quantise(value)
    if quantised == 0:
        exact = Decimal(str(float(value)))
        if exact == 0:
            return "0"
        return "<+0.01" if exact > 0 else "<-0.01"
    body = format_number(value)
    return f"+{body}" if quantised > 0 else body
