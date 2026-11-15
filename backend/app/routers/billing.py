"""Invoicing: list, inspect, price, raise, and print."""

import datetime as dt
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import (
    CreditNote,
    Invoice,
    InvoiceLine,
    PaymentAllocation,
    Product,
    Retailer,
)
from ..money import ZERO, q2
from ..schemas import InvoiceIn, InvoiceLineOut, InvoiceOut, InvoicePreviewIn
from ..services import billing, receivables, stock
from ..services.gst import amount_in_words
from ..services.invoice_pdf import build_cash_memo_pdf, build_invoice_pdf
from ..services.stock import InsufficientStock

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


def _paid_amount(db: Session, invoice_id: int) -> Decimal:
    total = db.execute(
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
            PaymentAllocation.invoice_id == invoice_id
        )
    ).scalar_one()
    return q2(total or 0)


def _credited_amount(db: Session, invoice_id: int) -> Decimal:
    """Credit notes reduce the balance exactly as payments do."""
    total = db.execute(
        select(func.coalesce(func.sum(CreditNote.grand_total), 0)).where(
            CreditNote.invoice_id == invoice_id
        )
    ).scalar_one()
    return q2(total or 0)


def _line_out(line: InvoiceLine) -> InvoiceLineOut:
    """Flatten a sold line, its product and the batches that satisfied it."""
    return InvoiceLineOut(
        id=line.id,
        product_id=line.product_id,
        sku_code=line.product.sku_code,
        product_name=line.product.display_name,
        hsn=line.hsn,
        cases=line.cases,
        loose_pieces=line.loose_pieces,
        qty_pieces=line.qty_pieces,
        rate_per_piece=line.rate_per_piece,
        quoted_rate_per_piece=line.quoted_rate_per_piece,
        gross=line.gross,
        discount=line.discount,
        taxable=line.taxable,
        gst_rate=line.gst_rate,
        cgst=line.cgst,
        sgst=line.sgst,
        igst=line.igst,
        line_total=line.line_total,
        is_free=line.is_free,
        batches=[
            {
                "batch_no": alloc.batch.batch_no,
                "expiry_date": alloc.batch.expiry_date,
                "qty_pieces": alloc.qty_pieces,
            }
            for alloc in line.batch_allocations
        ],
    )


def _to_out(db: Session, invoice: Invoice, with_lines: bool = True) -> InvoiceOut:
    paid = _paid_amount(db, invoice.id)
    credited = _credited_amount(db, invoice.id)
    retailer = invoice.retailer
    out = InvoiceOut(
        id=invoice.id,
        invoice_no=invoice.invoice_no,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        retailer_id=invoice.retailer_id,
        retailer_name=retailer.shop_name,
        retailer_gstin=retailer.gstin,
        route_name=retailer.route.name if retailer.route else None,
        place_of_supply=invoice.place_of_supply,
        is_interstate=invoice.is_interstate,
        price_mode=invoice.price_mode,
        party_type=retailer.party_type,
        taxable_total=invoice.taxable_total,
        discount_total=invoice.discount_total,
        cgst_total=invoice.cgst_total,
        sgst_total=invoice.sgst_total,
        igst_total=invoice.igst_total,
        round_off=invoice.round_off,
        grand_total=invoice.grand_total,
        amount_paid=paid,
        credited=credited,
        balance=q2(Decimal(str(invoice.grand_total)) - paid - credited),
        status=invoice.status,
        note=invoice.note,
        delivery_id=invoice.delivery_id,
        delivery_no=invoice.delivery.delivery_no if invoice.delivery else None,
        amount_in_words=amount_in_words(Decimal(str(invoice.grand_total))),
    )
    if not with_lines:
        return out

    lines, buckets = [], {}
    for line in invoice.lines:
        lines.append(_line_out(line))
        key = (line.hsn, float(line.gst_rate))
        bucket = buckets.setdefault(
            key,
            {
                "hsn": line.hsn,
                "gst_rate": float(line.gst_rate),
                "taxable": ZERO,
                "cgst": ZERO,
                "sgst": ZERO,
                "igst": ZERO,
            },
        )
        bucket["taxable"] += Decimal(str(line.taxable))
        bucket["cgst"] += Decimal(str(line.cgst))
        bucket["sgst"] += Decimal(str(line.sgst))
        bucket["igst"] += Decimal(str(line.igst))

    summary = [
        {**b, "taxable": float(b["taxable"]), "cgst": float(b["cgst"]),
         "sgst": float(b["sgst"]), "igst": float(b["igst"])}
        for b in buckets.values()
    ]
    return out.model_copy(update={"lines": lines, "hsn_summary": summary})


@router.get("", response_model=list[InvoiceOut])
def list_invoices(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    retailer_id: int | None = None,
    route_id: int | None = None,
    search: str | None = None,
    unpaid_only: bool = False,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.retailer))
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
    )
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if retailer_id:
        stmt = stmt.where(Invoice.retailer_id == retailer_id)
    if route_id:
        stmt = stmt.join(Retailer).where(Retailer.route_id == route_id)
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.join(Retailer, isouter=True).where(
            or_(Invoice.invoice_no.ilike(needle), Retailer.shop_name.ilike(needle))
        )

    invoices = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    rows = [_to_out(db, inv, with_lines=False) for inv in invoices]
    if unpaid_only:
        rows = [r for r in rows if r.balance > 0]
    return rows


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "No such invoice.")
    return _to_out(db, invoice)


@router.post("/preview")
def preview_invoice(payload: InvoicePreviewIn, db: Session = Depends(get_db)):
    """Cost a basket without saving, for the live total on the billing screen."""
    retailer = db.get(Retailer, payload.retailer_id)
    if retailer is None:
        raise HTTPException(404, "No such retailer.")
    invoice_date = payload.invoice_date or dt.date.today()
    line_inputs = [line.model_dump() for line in payload.lines]

    # A preview should never fail just because a line is short. Price it
    # without reserving stock, then report any shortfall as a warning so the
    # biller can trim the quantity before committing.
    warnings = []
    for raw in line_inputs:
        product = db.get(Product, raw["product_id"])
        if product is None:
            continue
        asked = raw.get("cases", 0) * product.pieces_per_case + raw.get(
            "loose_pieces", 0
        )
        available = stock.sellable_pieces(db, product.id, invoice_date)
        if asked > available:
            warnings.append({
                "product_id": product.id,
                "product_name": product.display_name,
                "asked": asked,
                "available": available,
                "message": f"Only {available} pieces of {product.display_name} "
                "can be sold before expiry.",
            })

    try:
        priced = billing.price_invoice(
            db,
            retailer=retailer,
            line_inputs=line_inputs,
            invoice_date=invoice_date,
            allocate=not warnings,
            price_mode=payload.price_mode,
        )
    except InsufficientStock as exc:
        raise HTTPException(409, detail={
            "error": "insufficient_stock", "message": str(exc)
        }) from exc
    except billing.BillingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    totals = priced["totals"]
    outstanding = receivables.retailer_outstanding(db, retailer.id)
    limit = Decimal(str(retailer.credit_limit))
    return {
        "interstate": priced["interstate"],
        "price_mode": priced["price_mode"],
        "party_type": retailer.party_type,
        "lines": [
            {
                "product_id": p["product"].id,
                "product_name": p["product"].display_name,
                "qty_pieces": p["qty_pieces"],
                "cases": p["cases"],
                "loose_pieces": p["loose_pieces"],
                "rate_per_piece": float(p["calc"].rate_per_piece),
                "quoted_rate_per_piece": (
                    float(p["calc"].quoted_rate)
                    if p["calc"].quoted_rate is not None
                    else None
                ),
                "discount": float(p["calc"].discount),
                "taxable": float(p["calc"].taxable),
                "tax": float(p["calc"].tax),
                "line_total": float(p["calc"].line_total),
                "is_free": p["is_free"],
                "batches": [
                    {"batch_id": b, "qty_pieces": q} for b, q in p["allocation"]
                ],
            }
            for p in priced["lines"]
        ],
        "totals": {
            "taxable_total": float(totals.taxable_total),
            "discount_total": float(totals.discount_total),
            "cgst_total": float(totals.cgst_total),
            "sgst_total": float(totals.sgst_total),
            "igst_total": float(totals.igst_total),
            "round_off": float(totals.round_off),
            "grand_total": float(totals.grand_total),
        },
        "amount_in_words": priced["amount_in_words"],
        "stock_warnings": warnings,
        "credit": {
            "outstanding": float(outstanding),
            "limit": float(limit),
            "after_this_bill": float(outstanding + totals.grand_total),
            "would_exceed": bool(limit > 0 and outstanding + totals.grand_total > limit),
        },
    }


@router.post("", response_model=InvoiceOut, status_code=201)
def create_invoice(payload: InvoiceIn, db: Session = Depends(get_db)):
    try:
        invoice = billing.create_invoice(
            db,
            retailer_id=payload.retailer_id,
            line_inputs=[line.model_dump() for line in payload.lines],
            invoice_date=payload.invoice_date,
            note=payload.note,
            price_mode=payload.price_mode,
            delivery_id=payload.delivery_id,
        )
    except InsufficientStock as exc:
        # Also 409: well formed, but the godown cannot supply it. Caught here
        # explicitly, because it subclasses ValueError and would otherwise
        # fall through to the generic 422 below.
        raise HTTPException(
            409,
            detail={
                "error": "insufficient_stock",
                "message": str(exc),
                "product": exc.label,
                "asked": exc.asked,
                "available": exc.available,
            },
        ) from exc
    except billing.BillingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _to_out(db, invoice)


@router.get("/{invoice_id}/pdf")
def invoice_pdf(
    invoice_id: int,
    download: bool = False,
    format: str = "invoice",
    db: Session = Depends(get_db),
):
    """One sale, two possible pieces of paper.

    `format=invoice` is the GST tax invoice the firm keeps and files.
    `format=memo` is the plain slip the shop gets with the goods: same
    money, no GSTIN and no tax breakup. Which one is printed changes
    nothing in the database -- the sale, the tax and GSTR-1 are the same
    either way.
    """
    if format not in ("invoice", "memo"):
        raise HTTPException(
            422,
            "A bill prints either as the tax invoice or as the shop's cash "
            "memo. Ask for format=invoice or format=memo.",
        )
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "No such invoice.")
    company = billing.company(db)
    if format == "memo":
        pdf = build_cash_memo_pdf(invoice, company)
        name = f"{invoice.invoice_no.replace('/', '-')}-memo.pdf"
    else:
        pdf = build_invoice_pdf(invoice, company)
        name = f"{invoice.invoice_no.replace('/', '-')}.pdf"
    disposition = "attachment" if download else "inline"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}"
        },
    )


@router.get("/{invoice_id}/lines", response_model=list[InvoiceLineOut])
def invoice_lines(invoice_id: int, db: Session = Depends(get_db)):
    lines = db.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)
    ).scalars()
    return [_line_out(line) for line in lines]
