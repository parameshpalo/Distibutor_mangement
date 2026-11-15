"""Document numbering.

Invoice numbers follow the e-invoicing rules even though this app does not
do e-invoicing: at most 16 characters, alphanumeric with `/` and `-` only,
not starting with zero, unique and gapless within a financial year.

    BD/26-27/00001   -> 14 characters

That is not wasted caution. The rules are the GST portal's own constraints on
a document number, so a series that satisfies them is a series that can be
filed, uploaded or -- if the business ever crosses the turnover threshold --
registered, with nothing renumbered. A van run number is exempt: it is an
internal reference, not a GST document.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NumberSeries


def financial_year(on_date: dt.date) -> str:
    """Indian financial year label: 1 April to 31 March."""
    start = on_date.year if on_date.month >= 4 else on_date.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _next_sequence(db: Session, kind: str, on_date: dt.date) -> tuple[str, int]:
    fy = financial_year(on_date)
    stmt = select(NumberSeries).where(
        NumberSeries.kind == kind, NumberSeries.fy == fy
    )
    # No-op on SQLite, a real row lock on PostgreSQL.
    series = db.execute(stmt.with_for_update()).scalar_one_or_none()
    if series is None:
        series = NumberSeries(kind=kind, fy=fy, last_number=0)
        db.add(series)
        db.flush()
    series.last_number += 1
    db.flush()
    return fy, series.last_number


def next_invoice_no(db: Session, on_date: dt.date, prefix: str = "BD") -> str:
    fy, seq = _next_sequence(db, "invoice", on_date)
    number = f"{prefix}/{fy}/{seq:05d}"
    if len(number) > 16:
        raise ValueError(
            f"Invoice number {number!r} exceeds the 16-character IRN limit; "
            "shorten the invoice prefix in the company profile."
        )
    return number


def next_grn_no(db: Session, on_date: dt.date) -> str:
    fy, seq = _next_sequence(db, "grn", on_date)
    return f"GRN/{fy}/{seq:05d}"


def next_receipt_no(db: Session, on_date: dt.date) -> str:
    fy, seq = _next_sequence(db, "receipt", on_date)
    return f"RCP/{fy}/{seq:05d}"


def next_credit_note_no(db: Session, on_date: dt.date) -> str:
    """A credit note is a GST document, so it obeys the same 16-char rule."""
    fy, seq = _next_sequence(db, "credit_note", on_date)
    number = f"CN/{fy}/{seq:05d}"
    if len(number) > 16:
        raise ValueError(f"Credit note number {number!r} exceeds 16 characters.")
    return number


def next_order_no(db: Session, on_date: dt.date) -> str:
    fy, seq = _next_sequence(db, "order", on_date)
    return f"SO/{fy}/{seq:05d}"


def next_delivery_no(db: Session, on_date: dt.date) -> str:
    """One van run. Not a GST document, so no 16-character limit applies."""
    fy, seq = _next_sequence(db, "delivery", on_date)
    return f"VAN/{fy}/{seq:05d}"
