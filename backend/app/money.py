"""Exact money handling.

Rupee amounts are stored as integer paise and per-piece rates as integer
ten-thousandths, so SQL SUM() and AVG() stay exact and the schema moves to
PostgreSQL unchanged. All arithmetic happens in Decimal, never float.
"""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0.00")


def q2(value) -> Decimal:
    """Quantize to paise, rounding half-up as GST rules require."""
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def q4(value) -> Decimal:
    return Decimal(str(value)).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


class Money(TypeDecorator):
    """Rupees at 2 decimal places, persisted as paise."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int(q2(value).scaleb(2))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(value) / 100).quantize(TWO_PLACES)


class Rate(TypeDecorator):
    """Per-piece rates at 4 decimal places, persisted as 1/10000 units."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int(q4(value).scaleb(4))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(value) / 10000).quantize(FOUR_PLACES)
