"""Van runs: a label on bills, and a loading list derived from them.

The whole service is small on purpose. A van run owns nothing. It has a
number and a date, and bills point at it. Everything
else a screen wants to show -- what to load, what it is worth, how many
shops -- is a sum over those bills, computed on read.

Two consequences worth knowing before changing anything here:

* **Adding or removing a bill moves no stock.** The stock already left the
  godown when the bill was raised. Attaching it to a run is a filing
  decision, not a goods movement, so it is safe to undo.
* **There is no shortage.** Nothing is "loaded" in the ledger sense, so
  nothing can fail to come back. If goods go missing off a van, the next
  stock count finds it, not this module.

The loading list is therefore a packing slip: what to physically put in the
van so that every bill on it can be handed over.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import Delivery, Invoice, InvoiceLine, Product
from . import numbering


class DeliveryError(ValueError):
    """A problem the owner can act on, safe to show on screen."""


def _load(db: Session, delivery_id: int) -> Delivery:
    run = db.get(Delivery, delivery_id)
    if run is None:
        raise DeliveryError("That van run does not exist.")
    return run


def create_run(
    db: Session,
    *,
    run_date: dt.date | None = None,
    note: str | None = None,
) -> Delivery:
    """Start an empty run. Bills are attached to it afterwards."""
    run_date = run_date or dt.date.today()
    run = Delivery(
        delivery_no=numbering.next_delivery_no(db, run_date),
        delivery_date=run_date,
        note=note,
        status="open",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run(
    db: Session,
    delivery_id: int,
    *,
    note: str | None = None,
) -> Delivery:
    """Change the note. Never the bills."""
    run = _load(db, delivery_id)
    if note is not None:
        run.note = note.strip() or None
    db.commit()
    db.refresh(run)
    return run


def add_bill(db: Session, *, delivery_id: int, invoice_id: int) -> Delivery:
    """Put an already-raised bill on this run.

    Moves no stock. A bill that is already on another run is moved, not
    duplicated, because an invoice travels in one van or none.
    """
    run = _load(db, delivery_id)
    if run.status == "done":
        raise DeliveryError(
            f"{run.delivery_no} is finished. Bills cannot be added to it."
        )
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise DeliveryError("That bill does not exist.")
    if invoice.status == "cancelled":
        raise DeliveryError("A cancelled bill cannot go out on a van.")
    invoice.delivery_id = run.id
    db.commit()
    db.refresh(run)
    return run


def remove_bill(db: Session, *, delivery_id: int, invoice_id: int) -> Delivery:
    """Take a bill off the run. It becomes a solo bill the buyer collects.

    The bill itself is untouched: same number, same stock movement, same
    receivable. Only how it leaves the godown changes.
    """
    run = _load(db, delivery_id)
    if run.status == "done":
        raise DeliveryError(
            f"{run.delivery_no} is finished. Its bills can no longer be changed."
        )
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.delivery_id != run.id:
        raise DeliveryError("That bill is not on this run.")
    invoice.delivery_id = None
    db.commit()
    db.refresh(run)
    return run


def set_status(db: Session, *, delivery_id: int, status: str) -> Delivery:
    """Move the run along: open -> out -> done.

    A run with no bills cannot be sent out, because an empty van is not a
    delivery and the owner has almost certainly not finished adding to it.
    """
    run = _load(db, delivery_id)
    order = ("open", "out", "done")
    if status not in order:
        raise DeliveryError("A van run is open, out, or done.")
    if status == "out" and not run.bills:
        raise DeliveryError(
            f"{run.delivery_no} has no bills on it. Add the bills the van is "
            "carrying before sending it out."
        )
    if order.index(status) < order.index(run.status):
        raise DeliveryError(
            f"{run.delivery_no} is already {run.status}; a run does not go "
            "backwards. Start a new run instead."
        )
    run.status = status
    now = dt.datetime.now()
    if status == "out" and run.sent_at is None:
        run.sent_at = now
    if status == "done" and run.done_at is None:
        run.done_at = now
    db.commit()
    db.refresh(run)
    return run


def loading_list(db: Session, run: Delivery) -> dict:
    """What to put in the van, consolidated by product.

    One row per product across every bill on the run, so the loader walks
    the godown once rather than once per shop. This is a packing slip: the
    goods are already sold, so nothing here is checked against stock.
    """
    wanted: dict[int, int] = defaultdict(int)
    bill_ids = [bill.id for bill in run.bills if bill.status != "cancelled"]
    if bill_ids:
        rows = db.execute(
            select(InvoiceLine.product_id, func.sum(InvoiceLine.qty_pieces))
            .where(InvoiceLine.invoice_id.in_(bill_ids))
            .group_by(InvoiceLine.product_id)
        ).all()
        for product_id, pieces in rows:
            wanted[product_id] += int(pieces or 0)

    items = []
    total_pieces = 0
    total_cases = 0.0
    for product_id, pieces in wanted.items():
        product = db.get(Product, product_id)
        if product is None:
            continue
        per_case = product.pieces_per_case or 1
        cases, loose = divmod(pieces, per_case)
        total_pieces += pieces
        total_cases += pieces / per_case
        items.append({
            "product_id": product_id,
            "sku_code": product.sku_code,
            "name": product.display_name,
            "pieces": pieces,
            "cases": cases,
            "loose_pieces": loose,
            "pieces_per_case": per_case,
        })
    items.sort(key=lambda row: row["name"])
    return {
        "items": items,
        "total_pieces": total_pieces,
        "total_cases": round(total_cases, 2),
        "line_count": len(items),
    }


def run_summary(db: Session, run: Delivery) -> dict:
    """Everything a screen needs about one run, derived from its bills."""
    bills = [bill for bill in run.bills if bill.status != "cancelled"]
    load = loading_list(db, run)
    return {
        "id": run.id,
        "delivery_no": run.delivery_no,
        "delivery_date": run.delivery_date,
        "status": run.status,
        "note": run.note,
        "sent_at": run.sent_at,
        "done_at": run.done_at,
        "bill_count": len(bills),
        "shop_count": len({bill.retailer_id for bill in bills}),
        "value": float(sum(float(bill.grand_total) for bill in bills)),
        "total_pieces": load["total_pieces"],
        "total_cases": load["total_cases"],
        "bills": [
            {
                "id": bill.id,
                "invoice_no": bill.invoice_no,
                "invoice_date": bill.invoice_date,
                "retailer_id": bill.retailer_id,
                "shop_name": bill.retailer.shop_name,
                "address_line": bill.retailer.address_line,
                "phone": bill.retailer.phone,
                "grand_total": float(bill.grand_total),
                "pieces": sum(line.qty_pieces for line in bill.lines),
            }
            for bill in bills
        ],
    }


def list_runs(db: Session, *, limit: int = 30, status: str | None = None) -> list[dict]:
    """Recent runs, newest first, each with its derived totals."""
    stmt = (
        select(Delivery)
        .options(selectinload(Delivery.bills).selectinload(Invoice.lines))
        .order_by(Delivery.delivery_date.desc(), Delivery.id.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Delivery.status == status)
    return [run_summary(db, run) for run in db.execute(stmt).scalars()]


def open_runs(db: Session, on_date: dt.date | None = None) -> list[Delivery]:
    """Runs a new bill could join: anything not finished, newest first.

    This is what the billing screen offers in its "deliver by van" picker.
    It is deliberately not filtered by date. A run left open from a previous
    day is exactly the thing the owner needs to see -- hiding it does not
    close it, it just means the bill goes on a second van nobody loaded.
    """
    return list(
        db.execute(
            select(Delivery)
            .where(Delivery.status != "done")
            .order_by(Delivery.delivery_date.desc(), Delivery.id.desc())
        ).scalars()
    )
