"""Collections: receipts, their allocation to invoices, and what is owed."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PAYMENT_MODES, Invoice, Payment, PaymentAllocation, Retailer
from ..money import q2
from ..schemas import OpenInvoiceOut, PaymentIn, PaymentOut
from ..services import numbering, receivables

router = APIRouter(prefix="/api", tags=["collections"])


def _payment_out(payment: Payment, note: str | None = None) -> PaymentOut:
    """Flatten a receipt and the invoices it was applied to."""
    return PaymentOut(
        id=payment.id,
        receipt_no=payment.receipt_no,
        retailer_id=payment.retailer_id,
        retailer_name=payment.retailer.shop_name,
        payment_date=payment.payment_date,
        mode=payment.mode,
        amount=payment.amount,
        reference=payment.reference,
        note=note if note is not None else payment.note,
        allocations=[
            {
                "invoice_id": a.invoice_id,
                "invoice_no": a.invoice.invoice_no,
                "amount": float(a.amount),
            }
            for a in payment.allocations
        ],
    )


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(
    retailer_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    limit: int = Query(default=50, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Payment).order_by(Payment.payment_date.desc(), Payment.id.desc())
    if retailer_id:
        stmt = stmt.where(Payment.retailer_id == retailer_id)
    if date_from:
        stmt = stmt.where(Payment.payment_date >= date_from)
    if date_to:
        stmt = stmt.where(Payment.payment_date <= date_to)

    payments = db.execute(stmt.limit(limit)).scalars().all()
    return [_payment_out(p) for p in payments]


@router.get("/retailers/{retailer_id}/open-invoices", response_model=list[OpenInvoiceOut])
def open_invoices(retailer_id: int, db: Session = Depends(get_db)):
    """Unpaid invoices, oldest first — the order a collection is applied in."""
    if db.get(Retailer, retailer_id) is None:
        raise HTTPException(404, "No such retailer.")
    return [
        OpenInvoiceOut.model_validate(row)
        for row in receivables.invoice_balances(
            db, retailer_id=retailer_id, only_open=True
        )
    ]


@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(payload: PaymentIn, db: Session = Depends(get_db)):
    """Record a collection and apply it to invoices.

    With no allocations supplied the money goes against the oldest open
    invoices first, which is how a collection at the shop actually works.
    """
    retailer = db.get(Retailer, payload.retailer_id)
    if retailer is None:
        raise HTTPException(404, "No such retailer.")
    if payload.mode not in PAYMENT_MODES:
        raise HTTPException(
            422, f"Payment mode must be one of: {', '.join(PAYMENT_MODES)}."
        )

    payment_date = payload.payment_date or dt.date.today()
    amount = q2(payload.amount)

    if payload.allocations:
        plan = [(a.invoice_id, q2(a.amount)) for a in payload.allocations]
        if q2(sum(amt for _, amt in plan)) > amount:
            raise HTTPException(
                422, "Allocations add up to more than the payment amount."
            )
        open_balances = {
            row["id"]: row["balance"]
            for row in receivables.invoice_balances(
                db, retailer_id=retailer.id, only_open=True
            )
        }
        for invoice_id, allocated in plan:
            invoice = db.get(Invoice, invoice_id)
            if invoice is None or invoice.retailer_id != retailer.id:
                raise HTTPException(
                    422, f"Invoice {invoice_id} does not belong to this retailer."
                )
            available = open_balances.get(invoice_id, Decimal("0"))
            if allocated > available:
                raise HTTPException(
                    422,
                    f"{invoice.invoice_no} has only {available:,.2f} outstanding; "
                    f"cannot allocate {allocated:,.2f}.",
                )
    else:
        plan = receivables.auto_allocate(db, retailer.id, amount)

    allocated_total = q2(sum((amt for _, amt in plan), Decimal("0")))
    payment = Payment(
        receipt_no=numbering.next_receipt_no(db, payment_date),
        retailer_id=retailer.id,
        payment_date=payment_date,
        mode=payload.mode,
        amount=amount,
        reference=payload.reference,
        note=payload.note,
    )
    db.add(payment)
    db.flush()
    for invoice_id, allocated in plan:
        if allocated <= 0:
            continue
        db.add(
            PaymentAllocation(
                payment_id=payment.id, invoice_id=invoice_id, amount=allocated
            )
        )
    db.commit()
    db.refresh(payment)

    # An on-account surplus is normal; say so rather than hiding it.
    note = payment.note
    if allocated_total < amount:
        surplus = float(amount - allocated_total)
        note = (
            f"{payment.note} | " if payment.note else ""
        ) + f"Rs {surplus:,.2f} unallocated (no further open invoices)"
    return _payment_out(payment, note=note)


@router.get("/outstanding")
def outstanding(db: Session = Depends(get_db)):
    """Ageing buckets, worst debtors, and anyone past their credit limit."""
    return receivables.ageing_report(db, dt.date.today())
