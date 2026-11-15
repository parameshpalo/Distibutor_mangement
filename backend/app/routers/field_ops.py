"""Orders, load sheets and credit notes.

The day plan and call logging have been removed: in a one-van business the
route itself is the day plan, and nobody logs a call that produced nothing.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    CREDIT_NOTE_REASONS,
    CreditNote,
    Invoice,
    Order,
)
from ..schemas import CreditNoteIn, OrderIn
from ..services import credits, orders as order_service
from ..services.billing import BillingError
from ..services.stock import InsufficientStock

router = APIRouter(prefix="/api", tags=["operations"])


def _order_out(order: Order) -> dict:
    return {
        "id": order.id,
        "order_no": order.order_no,
        "order_date": order.order_date,
        "requested_for": order.requested_for,
        "status": order.status,
        "retailer_id": order.retailer_id,
        "shop_name": order.retailer.shop_name,
        "route": order.route.name if order.route else None,
        "route_id": order.route_id,
        "estimated_value": float(order.estimated_value),
        "note": order.note,
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "sku_code": line.product.sku_code,
                "product_name": line.product.display_name,
                "cases": line.cases,
                "loose_pieces": line.loose_pieces,
                "qty_pieces": line.qty_pieces,
                "is_free": line.is_free,
            }
            for line in order.lines
        ],
    }


@router.get("/orders")
def list_orders(
    status: str | None = None,
    route_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Order).order_by(Order.order_date.desc(), Order.id.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    if route_id:
        stmt = stmt.where(Order.route_id == route_id)
    if date_from:
        stmt = stmt.where(Order.order_date >= date_from)
    if date_to:
        stmt = stmt.where(Order.order_date <= date_to)
    return [_order_out(order) for order in db.execute(stmt.limit(limit)).scalars()]


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "No such order.")
    return {
        **_order_out(order),
        "availability": order_service.order_availability(db, order, dt.date.today()),
    }


@router.post("/orders", status_code=201)
def capture_order(payload: OrderIn, db: Session = Depends(get_db)):
    try:
        order = order_service.capture_order(
            db,
            retailer_id=payload.retailer_id,
            lines=[line.model_dump() for line in payload.lines],
            order_date=payload.order_date,
            requested_for=payload.requested_for,
            note=payload.note,
        )
    except order_service.OrderError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _order_out(order)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, reason: str | None = None, db: Session = Depends(get_db)):
    try:
        return _order_out(order_service.cancel_order(db, order_id, reason))
    except order_service.OrderError as exc:
        raise HTTPException(422, str(exc)) from exc


# --- load sheets -----------------------------------------------------------


# --- credit notes ----------------------------------------------------------


@router.get("/credit-notes/reasons")
def credit_note_reasons():
    return [
        {
            "value": value,
            "label": value.replace("_", " ").capitalize(),
            "restocks": value in credits.RESTOCK_REASONS,
        }
        for value in CREDIT_NOTE_REASONS
    ]


@router.get("/credit-notes")
def list_credit_notes(
    limit: int = Query(default=50, le=300), db: Session = Depends(get_db)
):
    rows = db.execute(
        select(CreditNote)
        .order_by(CreditNote.note_date.desc(), CreditNote.id.desc())
        .limit(limit)
    ).scalars()
    return [credits.credit_note_detail(db, row) for row in rows]


@router.get("/credit-notes/{note_id}")
def get_credit_note(note_id: int, db: Session = Depends(get_db)):
    row = db.get(CreditNote, note_id)
    if row is None:
        raise HTTPException(404, "No such credit note.")
    return credits.credit_note_detail(db, row)


@router.get("/invoices/{invoice_id}/returnable")
def returnable(invoice_id: int, db: Session = Depends(get_db)):
    """What is still open to credit on an invoice."""
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "No such invoice.")
    return {
        "invoice_id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "invoice_date": invoice.invoice_date,
        "retailer_name": invoice.retailer.shop_name,
        "is_interstate": invoice.is_interstate,
        "lines": credits.returnable(db, invoice),
    }


@router.post("/credit-notes", status_code=201)
def create_credit_note(payload: CreditNoteIn, db: Session = Depends(get_db)):
    try:
        note = credits.create_credit_note(
            db,
            invoice_id=payload.invoice_id,
            reason=payload.reason,
            lines=[line.model_dump() for line in payload.lines],
            note_date=payload.note_date,
            note=payload.note,
        )
    except credits.CreditNoteError as exc:
        raise HTTPException(422, str(exc)) from exc
    return credits.credit_note_detail(db, note)


@router.get("/damage-register")
def damage_register(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    db: Session = Depends(get_db),
):
    """Stock written off as damaged, to claim against the company."""
    return credits.damage_register(db, date_from, date_to)
