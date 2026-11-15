"""Inventory: stock on hand, the movement ledger, and goods inward."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Product,
    Purchase,
    PurchaseLine,
    StockBatch,
    StockLedger,
)
from ..money import q2
from ..schemas import PurchaseIn, PurchaseLineOut, PurchaseOut
from ..services import numbering, stock
from ..services.gst import compute_line, rate_for_hsn

router = APIRouter(prefix="/api", tags=["inventory"])


@router.get("/stock")
def get_stock(
    search: str | None = None,
    risk: str | None = Query(default=None, pattern="^(near_expiry|expired|low_cover)$"),
    db: Session = Depends(get_db),
):
    """Stock by product, with batches, expiry risk and days of cover."""
    rows = stock.stock_snapshot(db, dt.date.today())

    if search:
        needle = search.strip().lower()
        rows = [
            r
            for r in rows
            if needle in r["name"].lower() or needle in r["sku_code"].lower()
        ]
    if risk == "near_expiry":
        rows = [r for r in rows if r["near_expiry_pieces"] > 0]
    elif risk == "expired":
        rows = [r for r in rows if r["expired_pieces"] > 0]
    elif risk == "low_cover":
        rows = [
            r for r in rows if r["cover_days"] is not None and r["cover_days"] < 10
        ]

    return {
        "as_of": dt.date.today(),
        "totals": {
            "skus": len(rows),
            "pieces": sum(r["pieces"] for r in rows),
            "value": round(sum(r["value"] for r in rows), 2),
            "near_expiry_value": round(sum(r["near_expiry_value"] for r in rows), 2),
            "expired_pieces": sum(r["expired_pieces"] for r in rows),
        },
        "items": rows,
    }


@router.get("/stock/ledger")
def get_ledger(
    product_id: int | None = None,
    batch_id: int | None = None,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
):
    """The raw movement trail, newest first.

    Every row is a movement in or out of the godown. There is no second
    place for stock to be: once a bill is raised the goods are sold, whether
    the buyer carries them away or they go out on one of the firm's vans.
    """
    stmt = select(StockLedger).order_by(
        StockLedger.occurred_on.desc(), StockLedger.id.desc()
    )
    if product_id:
        stmt = stmt.where(StockLedger.product_id == product_id)
    if batch_id:
        stmt = stmt.where(StockLedger.batch_id == batch_id)

    entries = db.execute(stmt.limit(limit)).scalars().all()
    return [
        {
            "id": e.id,
            "occurred_on": e.occurred_on,
            "product_id": e.product_id,
            "product_name": e.product.display_name,
            "batch_no": e.batch.batch_no,
            "expiry_date": e.batch.expiry_date,
            "qty_pieces": e.qty_pieces,
            "direction": "in" if e.qty_pieces > 0 else "out",
            "reason": e.reason,
            "ref_type": e.ref_type,
            "ref_id": e.ref_id,
            "note": e.note,
        }
        for e in entries
    ]


def _line_out(line: PurchaseLine) -> PurchaseLineOut:
    """Flatten a GRN line and the batch it created into one row."""
    return PurchaseLineOut(
        product_id=line.product_id,
        product_name=line.product.display_name,
        sku_code=line.product.sku_code,
        batch_no=line.batch.batch_no,
        mfg_date=line.batch.mfg_date,
        expiry_date=line.batch.expiry_date,
        cases=line.cases,
        loose_pieces=line.loose_pieces,
        qty_pieces=line.qty_pieces,
        rate_per_piece=line.rate_per_piece,
        taxable=line.taxable,
        tax_amount=line.tax_amount,
        line_total=line.line_total,
    )


def _purchase_out(purchase: Purchase, with_lines: bool = True) -> PurchaseOut:
    return PurchaseOut(
        id=purchase.id,
        grn_no=purchase.grn_no,
        supplier_name=purchase.supplier_name,
        company_invoice_no=purchase.company_invoice_no,
        company_invoice_date=purchase.company_invoice_date,
        received_on=purchase.received_on,
        taxable_total=purchase.taxable_total,
        tax_total=purchase.tax_total,
        grand_total=purchase.grand_total,
        line_count=len(purchase.lines),
        note=purchase.note,
        lines=[_line_out(line) for line in purchase.lines] if with_lines else [],
    )


@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(
    limit: int = Query(default=50, le=500), db: Session = Depends(get_db)
):
    rows = (
        db.execute(
            select(Purchase)
            .order_by(Purchase.received_on.desc(), Purchase.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_purchase_out(p, with_lines=False) for p in rows]


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
def get_purchase(purchase_id: int, db: Session = Depends(get_db)):
    purchase = db.get(Purchase, purchase_id)
    if purchase is None:
        raise HTTPException(404, "No such GRN.")
    return _purchase_out(purchase)


@router.post("/purchases", response_model=PurchaseOut, status_code=201)
def create_purchase(payload: PurchaseIn, db: Session = Depends(get_db)):
    """Receive goods: create or reuse batches and post inward movements."""
    purchase = Purchase(
        grn_no=numbering.next_grn_no(db, payload.received_on),
        supplier_name=payload.supplier_name,
        company_invoice_no=payload.company_invoice_no,
        company_invoice_date=payload.company_invoice_date,
        received_on=payload.received_on,
        note=payload.note,
    )
    db.add(purchase)
    db.flush()

    taxable_total = Decimal("0.00")
    tax_total = Decimal("0.00")

    for line_in in payload.lines:
        product = db.get(Product, line_in.product_id)
        if product is None or not product.is_active:
            raise HTTPException(422, f"Product {line_in.product_id} is not available.")

        qty = line_in.cases * product.pieces_per_case + line_in.loose_pieces
        if qty <= 0:
            raise HTTPException(
                422, f"{product.display_name}: enter a quantity in cases or pieces."
            )

        expiry = line_in.expiry_date or (
            line_in.mfg_date + dt.timedelta(days=product.shelf_life_days)
        )
        if expiry <= line_in.mfg_date:
            raise HTTPException(
                422,
                f"{product.display_name}: expiry {expiry} is not after "
                f"manufacture {line_in.mfg_date}.",
            )
        if expiry < payload.received_on:
            raise HTTPException(
                422,
                f"{product.display_name}: batch {line_in.batch_no} has already "
                f"expired on {expiry:%d-%b-%Y}; do not take it into stock.",
            )

        rate = Decimal(str(line_in.rate_per_piece or product.ptd))
        batch = db.execute(
            select(StockBatch).where(
                StockBatch.product_id == product.id,
                StockBatch.batch_no == line_in.batch_no,
            )
        ).scalar_one_or_none()
        if batch is None:
            batch = StockBatch(
                product_id=product.id,
                batch_no=line_in.batch_no,
                mfg_date=line_in.mfg_date,
                expiry_date=expiry,
                cost_per_piece=rate,
            )
            db.add(batch)
            db.flush()

        gst_rate = rate_for_hsn(db, product.hsn, payload.received_on)
        calc = compute_line(
            qty_pieces=qty,
            rate_per_piece=rate,
            gst_rate=gst_rate,
            is_interstate=False,
        )
        db.add(
            PurchaseLine(
                purchase_id=purchase.id,
                product_id=product.id,
                batch_id=batch.id,
                cases=line_in.cases,
                loose_pieces=line_in.loose_pieces,
                qty_pieces=qty,
                rate_per_piece=rate,
                taxable=calc.taxable,
                gst_rate=gst_rate,
                tax_amount=calc.tax,
                line_total=calc.line_total,
            )
        )
        stock.post_movement(
            db,
            product_id=product.id,
            batch_id=batch.id,
            qty_pieces=qty,
            reason="grn",
            occurred_on=payload.received_on,
            ref_type="purchase",
            ref_id=purchase.id,
        )
        taxable_total += calc.taxable
        tax_total += calc.tax

    purchase.taxable_total = q2(taxable_total)
    purchase.tax_total = q2(tax_total)
    purchase.grand_total = q2(taxable_total + tax_total)
    db.commit()
    db.refresh(purchase)
    return get_purchase(purchase.id, db)
