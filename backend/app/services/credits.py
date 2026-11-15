"""Credit notes: returns, shortages and rate differences.

Three rules shape this file.

**Tax is reversed at the rate the invoice used**, not today's rate. A credit
note is a correction to a past supply, so it inherits that supply's slab and
its intrastate or interstate character.

**Saleable stock goes back to the batch it left on.** Returns are matched
against the invoice's own batch allocation, so a returned case re-enters
with its real expiry rather than as anonymous stock.

**Damaged stock never re-enters saleable stock.** It is recorded coming back
and written off in the same breath, which nets to nothing on hand but leaves
a damage register to claim against the company.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CREDIT_NOTE_REASONS,
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    StockLedger,
)
from ..money import ZERO, q2
from . import numbering, stock
from .gst import RUPEE, amount_in_words

#: Reasons whose goods come back fit to sell again.
RESTOCK_REASONS = {"return_saleable", "near_expiry_return"}


class CreditNoteError(ValueError):
    """Something the person raising the note can fix."""


def returned_so_far(db: Session, invoice_id: int) -> dict[int, int]:
    """Pieces already credited per invoice line."""
    rows = db.execute(
        select(
            CreditNoteLine.invoice_line_id,
            func.coalesce(func.sum(CreditNoteLine.qty_pieces), 0),
        )
        .join(CreditNote, CreditNote.id == CreditNoteLine.credit_note_id)
        .where(CreditNote.invoice_id == invoice_id)
        .group_by(CreditNoteLine.invoice_line_id)
    ).all()
    return {line_id: int(qty) for line_id, qty in rows}


def returnable(db: Session, invoice: Invoice) -> list[dict]:
    """What is still open to credit on an invoice, line by line."""
    already = returned_so_far(db, invoice.id)
    rows = []
    for line in invoice.lines:
        done = already.get(line.id, 0)
        rows.append(
            {
                "invoice_line_id": line.id,
                "product_id": line.product_id,
                "sku_code": line.product.sku_code,
                "product_name": line.product.display_name,
                "hsn": line.hsn,
                "sold_pieces": line.qty_pieces,
                "pieces_per_case": line.product.pieces_per_case,
                "returned_pieces": done,
                "returnable_pieces": max(line.qty_pieces - done, 0),
                "rate_per_piece": float(line.rate_per_piece),
                "gst_rate": float(line.gst_rate),
                "is_free": line.is_free,
            }
        )
    return rows


def _restock_plan(db: Session, line: InvoiceLine, pieces: int) -> list[tuple[int, int]]:
    """Put returns back on the batches this line went out on.

    Works through the original allocation oldest-expiry first, which is
    where a shop's unsold stock most likely came from.
    """
    allocations = sorted(
        line.batch_allocations, key=lambda a: (a.batch.expiry_date, a.batch_id)
    )
    plan: list[tuple[int, int]] = []
    remaining = pieces
    for allocation in allocations:
        if remaining <= 0:
            break
        take = min(allocation.qty_pieces, remaining)
        plan.append((allocation.batch_id, take))
        remaining -= take
    if remaining > 0 and allocations:
        # More coming back than the batch split accounts for: put the
        # remainder on the last batch rather than inventing a new one.
        batch_id, qty = plan[-1]
        plan[-1] = (batch_id, qty + remaining)
    return plan


def create_credit_note(
    db: Session,
    *,
    invoice_id: int,
    reason: str,
    lines: list[dict],
    note_date: dt.date | None = None,
    note: str | None = None,
) -> CreditNote:
    """Raise a credit note against an invoice and move the stock it implies."""
    if reason not in CREDIT_NOTE_REASONS:
        raise CreditNoteError(
            f"Reason must be one of: {', '.join(CREDIT_NOTE_REASONS)}."
        )

    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise CreditNoteError("No such invoice.")
    if invoice.status != "issued":
        raise CreditNoteError(
            f"Invoice {invoice.invoice_no} is {invoice.status}; "
            "only an issued invoice can be credited."
        )

    note_date = note_date or dt.date.today()
    if note_date < invoice.invoice_date:
        raise CreditNoteError(
            "A credit note cannot predate the invoice it corrects."
        )

    already = returned_so_far(db, invoice.id)
    by_line = {line.id: line for line in invoice.lines}
    restock = reason in RESTOCK_REASONS

    prepared = []
    for raw in lines:
        line = by_line.get(raw["invoice_line_id"])
        if line is None:
            raise CreditNoteError(
                f"Line {raw['invoice_line_id']} is not on {invoice.invoice_no}."
            )
        per_case = line.product.pieces_per_case
        pieces = (
            int(raw.get("cases") or 0) * per_case + int(raw.get("loose_pieces") or 0)
        )
        if pieces <= 0:
            continue
        open_qty = line.qty_pieces - already.get(line.id, 0)
        if pieces > open_qty:
            raise CreditNoteError(
                f"{line.product.display_name}: {pieces} pieces exceeds the "
                f"{open_qty} still open on {invoice.invoice_no}."
            )
        prepared.append((line, raw, pieces))

    if not prepared:
        raise CreditNoteError("A credit note needs at least one line with a quantity.")

    credit = CreditNote(
        note_no=numbering.next_credit_note_no(db, note_date),
        note_date=note_date,
        invoice_id=invoice.id,
        retailer_id=invoice.retailer_id,
        reason=reason,
        is_interstate=invoice.is_interstate,
        place_of_supply=invoice.place_of_supply,
        note=note,
    )
    db.add(credit)
    db.flush()

    taxable_total = cgst_total = sgst_total = igst_total = ZERO

    for line, raw, pieces in prepared:
        rate = Decimal(str(line.rate_per_piece))
        gst_rate = Decimal(str(line.gst_rate))

        # Credit the line's effective rate, so a discounted sale is
        # credited at what was actually charged, not at list price.
        if line.is_free or line.qty_pieces == 0:
            taxable = ZERO
        else:
            effective = Decimal(str(line.taxable)) / line.qty_pieces
            taxable = q2(effective * pieces)

        if invoice.is_interstate:
            igst = q2(taxable * gst_rate / 100)
            cgst = sgst = ZERO
        else:
            half = gst_rate / 2
            cgst = q2(taxable * half / 100)
            sgst = cgst
            igst = ZERO

        db.add(
            CreditNoteLine(
                credit_note_id=credit.id,
                invoice_line_id=line.id,
                product_id=line.product_id,
                hsn=line.hsn,
                cases=int(raw.get("cases") or 0),
                loose_pieces=int(raw.get("loose_pieces") or 0),
                qty_pieces=pieces,
                restock=restock,
                rate_per_piece=rate,
                taxable=taxable,
                gst_rate=gst_rate,
                cgst=cgst,
                sgst=sgst,
                igst=igst,
                line_total=q2(taxable + cgst + sgst + igst),
            )
        )

        taxable_total += taxable
        cgst_total += cgst
        sgst_total += sgst
        igst_total += igst

        # Move the goods.
        for batch_id, qty in _restock_plan(db, line, pieces):
            if restock:
                stock.post_movement(
                    db,
                    product_id=line.product_id,
                    batch_id=batch_id,
                    qty_pieces=qty,
                    reason="sale_return_saleable",
                    occurred_on=note_date,
                    ref_type="credit_note",
                    ref_id=credit.id,
                    note=f"Return against {invoice.invoice_no}",
                )
            elif reason == "return_damaged":
                # Back in, then written off: nets to nothing on hand, but
                # both the return and the loss stay on the record.
                stock.post_movement(
                    db,
                    product_id=line.product_id,
                    batch_id=batch_id,
                    qty_pieces=qty,
                    reason="sale_return_damaged",
                    occurred_on=note_date,
                    ref_type="credit_note",
                    ref_id=credit.id,
                    note=f"Damaged return against {invoice.invoice_no}",
                )
                stock.post_movement(
                    db,
                    product_id=line.product_id,
                    batch_id=batch_id,
                    qty_pieces=-qty,
                    reason="damage",
                    occurred_on=note_date,
                    ref_type="credit_note",
                    ref_id=credit.id,
                    note="Written off; claim against the company",
                )
            # A shortage or rate difference moves no goods at all: the stock
            # never reached the shop, or only the price was wrong.

    subtotal = q2(taxable_total + cgst_total + sgst_total + igst_total)
    rounded = subtotal.quantize(RUPEE)
    credit.taxable_total = q2(taxable_total)
    credit.cgst_total = q2(cgst_total)
    credit.sgst_total = q2(sgst_total)
    credit.igst_total = q2(igst_total)
    credit.round_off = q2(rounded - subtotal)
    credit.grand_total = q2(rounded)

    db.commit()
    db.refresh(credit)
    return credit


def credit_note_detail(db: Session, credit: CreditNote) -> dict:
    return {
        "id": credit.id,
        "note_no": credit.note_no,
        "note_date": credit.note_date,
        "reason": credit.reason,
        "invoice_id": credit.invoice_id,
        "invoice_no": credit.invoice.invoice_no,
        "invoice_date": credit.invoice.invoice_date,
        "retailer_id": credit.retailer_id,
        "retailer_name": credit.retailer.shop_name,
        "retailer_gstin": credit.retailer.gstin,
        "is_interstate": credit.is_interstate,
        "place_of_supply": credit.place_of_supply,
        "taxable_total": float(credit.taxable_total),
        "cgst_total": float(credit.cgst_total),
        "sgst_total": float(credit.sgst_total),
        "igst_total": float(credit.igst_total),
        "round_off": float(credit.round_off),
        "grand_total": float(credit.grand_total),
        "amount_in_words": amount_in_words(Decimal(str(credit.grand_total))),
        "note": credit.note,
        "restocked": credit.reason in RESTOCK_REASONS,
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "product_name": line.product.display_name,
                "sku_code": line.product.sku_code,
                "hsn": line.hsn,
                "cases": line.cases,
                "loose_pieces": line.loose_pieces,
                "qty_pieces": line.qty_pieces,
                "restock": line.restock,
                "rate_per_piece": float(line.rate_per_piece),
                "taxable": float(line.taxable),
                "gst_rate": float(line.gst_rate),
                "cgst": float(line.cgst),
                "sgst": float(line.sgst),
                "igst": float(line.igst),
                "line_total": float(line.line_total),
            }
            for line in credit.lines
        ],
    }


def damage_register(
    db: Session, date_from: dt.date | None = None, date_to: dt.date | None = None
) -> dict:
    """Everything written off as damaged, to claim against the company."""
    stmt = select(StockLedger).where(StockLedger.reason == "damage")
    if date_from:
        stmt = stmt.where(StockLedger.occurred_on >= date_from)
    if date_to:
        stmt = stmt.where(StockLedger.occurred_on <= date_to)

    rows = []
    total_pieces = 0
    total_value = ZERO
    for entry in db.execute(stmt.order_by(StockLedger.occurred_on.desc())).scalars():
        pieces = abs(entry.qty_pieces)
        value = q2(Decimal(str(entry.batch.cost_per_piece)) * pieces)
        total_pieces += pieces
        total_value += value
        rows.append(
            {
                "id": entry.id,
                "occurred_on": entry.occurred_on,
                "product_name": entry.product.display_name,
                "batch_no": entry.batch.batch_no,
                "expiry_date": entry.batch.expiry_date,
                "pieces": pieces,
                "cases": round(pieces / entry.product.pieces_per_case, 2),
                "value_at_cost": float(value),
                "ref_type": entry.ref_type,
                "ref_id": entry.ref_id,
                "note": entry.note,
            }
        )

    return {
        "entries": rows,
        "total_pieces": total_pieces,
        "total_value": float(q2(total_value)),
        "count": len(rows),
    }
