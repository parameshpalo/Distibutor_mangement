"""Orders taken at the shop, before anything is billed.

An order is a promise, not a document of record. It moves no stock and charges
no tax; both happen when it becomes an invoice. That separation is what lets an
order be taken at a counter with no risk of committing stock nobody can see.

Not every shop orders in advance, and that is fine: a stop on a route with no
order is billed at the counter from what the van is carrying. So an order is an
optional convenience here, never a precondition for a sale.

This file used to also record every call, with a reason when nothing was
bought. That has been removed: nobody in a one-van business logs calls, and a
"productive call rate" measured from data nobody enters is worse than no
figure at all.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Order, OrderLine, Product, Retailer
from ..money import ZERO, q2
from . import numbering, stock


class OrderError(ValueError):
    """Something the person taking the order can fix at the shop."""


def estimate_value(
    db: Session, lines: list[dict], party_type: str = "retailer"
) -> Decimal:
    """Indicative order value at list price, before tax and any scheme.

    Deliberately not a quotation: the binding figure is struck when the
    invoice is raised, at the rates in force that day. A sub-distributor
    is costed at PTD so the figure read back at the shop is the one that
    party will actually be billed.
    """
    total = ZERO
    for raw in lines:
        if raw.get("is_free"):
            continue
        product = db.get(Product, raw["product_id"])
        if product is None:
            continue
        qty = raw.get("cases", 0) * product.pieces_per_case + raw.get(
            "loose_pieces", 0
        )
        rate = product.ptd if party_type == "distributor" else product.ptr
        total += q2(Decimal(str(rate)) * qty)
    return q2(total)


def capture_order(
    db: Session,
    *,
    retailer_id: int,
    lines: list[dict],
    order_date: dt.date | None = None,
    requested_for: dt.date | None = None,
    note: str | None = None,
) -> Order:
    """Take an order at the shop.

    Stock is checked for information only and never reserved: two routes may
    both promise the same cases, and loading the van is where that competition
    is resolved.
    """
    retailer = db.get(Retailer, retailer_id)
    if retailer is None or not retailer.is_active:
        raise OrderError("That retailer is not on the active list.")

    order_date = order_date or dt.date.today()
    prepared = []
    for raw in lines:
        product = db.get(Product, raw["product_id"])
        if product is None or not product.is_active:
            raise OrderError(f"Product {raw['product_id']} is not available.")
        qty = (
            int(raw.get("cases") or 0) * product.pieces_per_case
            + int(raw.get("loose_pieces") or 0)
        )
        if qty <= 0:
            raise OrderError(
                f"{product.display_name}: enter at least one case or some pieces."
            )
        prepared.append((product, raw, qty))

    if not prepared:
        raise OrderError("An order needs at least one line.")

    order = Order(
        order_no=numbering.next_order_no(db, order_date),
        retailer_id=retailer.id,
        route_id=retailer.route_id,
        order_date=order_date,
        requested_for=requested_for,
        status="pending",
        estimated_value=estimate_value(
            db,
            [{"product_id": p.id, **r} for p, r, _ in prepared],
            retailer.party_type,
        ),
        note=note,
    )
    db.add(order)
    db.flush()

    for product, raw, qty in prepared:
        db.add(
            OrderLine(
                order_id=order.id,
                product_id=product.id,
                cases=int(raw.get("cases") or 0),
                loose_pieces=int(raw.get("loose_pieces") or 0),
                qty_pieces=qty,
                is_free=bool(raw.get("is_free")),
            )
        )

    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order_id: int, reason: str | None = None) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise OrderError("No such order.")
    if order.status == "delivered":
        raise OrderError(
            f"{order.order_no} has already been delivered and billed; "
            "raise a credit note instead."
        )
    order.status = "cancelled"
    order.note = " | ".join(filter(None, [order.note, reason]))
    db.commit()
    db.refresh(order)
    return order


def order_availability(db: Session, order: Order, on_date: dt.date) -> list[dict]:
    """Per line, what is actually sellable right now.

    Read in the godown before loading, so a short line is spotted there rather
    than at the shop door. Reads the godown only: stock already out on another
    van is not available to load onto this one.
    """
    rows = []
    for line in order.lines:
        available = stock.sellable_pieces(db, line.product_id, on_date)
        rows.append(
            {
                "product_id": line.product_id,
                "product_name": line.product.display_name,
                "ordered_pieces": line.qty_pieces,
                "available_pieces": available,
                "short_by": max(line.qty_pieces - available, 0),
            }
        )
    return rows
