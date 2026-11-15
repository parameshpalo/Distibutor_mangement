"""What retailers owe, derived from invoices and their allocations.

Nothing here reads a stored balance. An invoice's balance is its total less
the payment slices allocated to it, which is why part-payments never drift
out of step with the ageing report.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CreditNote, Invoice, PaymentAllocation, Retailer
from ..money import ZERO, q2

# Upper bound of days overdue for each bucket; None is the catch-all.
AGEING_BUCKETS: tuple[tuple[str, int | None], ...] = (
    ("current", 0),
    ("1-7", 7),
    ("8-15", 15),
    ("16-30", 30),
    ("30+", None),
)


def _allocated_subquery():
    return (
        select(
            PaymentAllocation.invoice_id.label("invoice_id"),
            func.sum(PaymentAllocation.amount).label("paid"),
        )
        .group_by(PaymentAllocation.invoice_id)
        .subquery()
    )


def _credited_subquery():
    """Credit notes reduce what is owed just as a payment does."""
    return (
        select(
            CreditNote.invoice_id.label("invoice_id"),
            func.sum(CreditNote.grand_total).label("credited"),
        )
        .group_by(CreditNote.invoice_id)
        .subquery()
    )


def invoice_balances(
    db: Session,
    retailer_id: int | None = None,
    only_open: bool = True,
    as_of: dt.date | None = None,
) -> list[dict]:
    """Every invoice with what has been paid against it and what remains."""
    as_of = as_of or dt.date.today()
    paid = _allocated_subquery()
    credited = _credited_subquery()
    stmt = (
        select(
            Invoice,
            func.coalesce(paid.c.paid, 0).label("paid"),
            func.coalesce(credited.c.credited, 0).label("credited"),
        )
        .outerjoin(paid, paid.c.invoice_id == Invoice.id)
        .outerjoin(credited, credited.c.invoice_id == Invoice.id)
        .where(Invoice.status == "issued")
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
    )
    if retailer_id is not None:
        stmt = stmt.where(Invoice.retailer_id == retailer_id)

    rows = []
    for invoice, paid_amount, credited_amount in db.execute(stmt).all():
        total = Decimal(str(invoice.grand_total))
        settled = Decimal(str(paid_amount or 0))
        credit = Decimal(str(credited_amount or 0))
        balance = q2(total - settled - credit)
        if only_open and balance <= 0:
            continue
        rows.append(
            {
                "id": invoice.id,
                "invoice_no": invoice.invoice_no,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "retailer_id": invoice.retailer_id,
                "grand_total": total,
                "amount_paid": settled,
                "credited": credit,
                "balance": balance,
                "days_overdue": max((as_of - invoice.due_date).days, 0),
            }
        )
    return rows


def retailer_outstanding(db: Session, retailer_id: int) -> Decimal:
    """Total unpaid across a retailer's issued invoices."""
    rows = invoice_balances(db, retailer_id=retailer_id, only_open=True)
    return q2(sum((r["balance"] for r in rows), ZERO))


def bucket_for(days_overdue: int) -> str:
    for label, upper in AGEING_BUCKETS:
        if upper is None or days_overdue <= upper:
            return label
    return AGEING_BUCKETS[-1][0]


def ageing_report(db: Session, as_of: dt.date) -> dict:
    """Ageing buckets, the biggest debtors, and anyone past their limit."""
    open_rows = invoice_balances(db, only_open=True, as_of=as_of)

    buckets = {label: {"label": label, "amount": ZERO, "count": 0} for label, _ in AGEING_BUCKETS}
    per_retailer: dict[int, dict] = {}
    total = ZERO

    for row in open_rows:
        label = bucket_for(row["days_overdue"])
        buckets[label]["amount"] += row["balance"]
        buckets[label]["count"] += 1
        total += row["balance"]

        entry = per_retailer.setdefault(
            row["retailer_id"],
            {"retailer_id": row["retailer_id"], "balance": ZERO, "invoices": 0, "worst_overdue": 0},
        )
        entry["balance"] += row["balance"]
        entry["invoices"] += 1
        entry["worst_overdue"] = max(entry["worst_overdue"], row["days_overdue"])

    retailers: dict[int, Retailer] = {}
    if per_retailer:
        retailers = {
            r.id: r
            for r in db.execute(
                select(Retailer).where(Retailer.id.in_(list(per_retailer)))
            ).scalars()
        }

    debtors = []
    over_limit = []
    for entry in per_retailer.values():
        retailer = retailers.get(entry["retailer_id"])
        if retailer is None:
            continue
        limit = Decimal(str(retailer.credit_limit))
        record = {
            "retailer_id": retailer.id,
            "shop_name": retailer.shop_name,
            "route": retailer.route.name if retailer.route else None,
            "balance": float(q2(entry["balance"])),
            "invoices": entry["invoices"],
            "worst_overdue": entry["worst_overdue"],
            "credit_limit": float(limit),
            "utilisation": (
                round(float(entry["balance"] / limit) * 100, 1) if limit > 0 else None
            ),
        }
        debtors.append(record)
        if limit > 0 and entry["balance"] > limit:
            over_limit.append(record)

    over_limit.sort(key=lambda d: d["balance"] - d["credit_limit"], reverse=True)

    # Two orderings, because they answer different questions. By value tells
    # you where the money is; by age tells you which shop to chase, which is
    # the one the Money page leads with -- an old small debt is a worse sign
    # than a large new one.
    by_age = sorted(
        debtors, key=lambda d: (-d["worst_overdue"], -d["balance"])
    )
    by_value = sorted(debtors, key=lambda d: d["balance"], reverse=True)

    # Anything past its due date, which is every bucket but "current".
    overdue = sum(
        (b["amount"] for label, b in buckets.items() if label != "current"), ZERO
    )
    overdue_count = sum(
        b["count"] for label, b in buckets.items() if label != "current"
    )

    return {
        "total": float(q2(total)),
        "invoice_count": len(open_rows),
        "overdue": float(q2(overdue)),
        "overdue_count": overdue_count,
        "buckets": [
            {"label": b["label"], "amount": float(q2(b["amount"])), "count": b["count"]}
            for b in buckets.values()
        ],
        "debtors": by_age,
        "top_debtors": by_value[:10],
        "over_limit": over_limit,
    }


def auto_allocate(
    db: Session, retailer_id: int, amount: Decimal
) -> list[tuple[int, Decimal]]:
    """Spread a payment over the oldest open invoices first.

    Returns (invoice_id, amount) pairs. Any excess beyond what is owed is
    left unallocated and reported back to the caller.
    """
    remaining = q2(amount)
    plan: list[tuple[int, Decimal]] = []
    for row in invoice_balances(db, retailer_id=retailer_id, only_open=True):
        if remaining <= 0:
            break
        take = min(row["balance"], remaining)
        plan.append((row["id"], q2(take)))
        remaining = q2(remaining - take)
    return plan
