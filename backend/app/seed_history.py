"""Demo history for orders, van runs and credit notes.

Invoices run the whole trading history, but orders only start a fortnight
back. That is deliberate and realistic: the office was billing long before
anyone started writing orders down in advance, and plenty of shops still
never order ahead -- they are billed at the counter from the van.
"""

from __future__ import annotations

import datetime as dt
import random
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Delivery,
    Invoice,
    Order,
    OrderLine,
    Product,
    Retailer,
    Route,
)
from .money import q2
from .services import credits, numbering

CREDIT_NOTE_NARRATIVE = {
    "return_saleable": "Unsold stock picked up on the next visit",
    "return_damaged": "Crushed in transit; claim raised with the company",
    "near_expiry_return": "Short-dated stock pulled back for redistribution",
    "shortage": "Short delivered; corrected on the next run",
}


def seed_order_history(
    db: Session,
    *,
    plan: list[dict],
    invoices: list[Invoice],
    today: dt.date,
    orders_since: dt.date,
    rng: random.Random,
) -> dict:
    """Orders and load sheets for the recent window."""
    by_shop_day: dict[tuple[dt.date, int], Invoice] = {
        (invoice.invoice_date, invoice.retailer_id): invoice for invoice in invoices
    }

    # --- orders, only for the recent window ---------------------------
    delivered: list[tuple[Order, Invoice]] = []
    for entry in sorted(plan, key=lambda o: (o["date"], o["retailer"].id)):
        if entry["date"] < orders_since:
            continue
        invoice = by_shop_day.get((entry["date"], entry["retailer"].id))
        if invoice is None:
            continue  # the planned order never became a bill
        order = Order(
            order_no=numbering.next_order_no(db, entry["date"]),
            retailer_id=entry["retailer"].id,
            route_id=entry["retailer"].route_id,
            order_date=entry["date"],
            requested_for=entry["date"],
            status="delivered",
            estimated_value=q2(Decimal(str(invoice.taxable_total))),
        )
        db.add(order)
        db.flush()
        for line in invoice.lines:
            db.add(
                OrderLine(
                    order_id=order.id,
                    product_id=line.product_id,
                    cases=line.cases,
                    loose_pieces=line.loose_pieces,
                    qty_pieces=line.qty_pieces,
                    is_free=line.is_free,
                )
            )
        invoice.order_id = order.id
        delivered.append((order, invoice))
    db.flush()

    # --- one van run per route per day -----------------------------------
    #
    # Reconstructed from the bills that were raised that day: a run is the
    # set of bills it carried, so grouping the day's invoices by route gives
    # back exactly the runs that went out. Marked done, because they did.
    grouped: dict[tuple[dt.date, int | None], list] = defaultdict(list)
    for order, invoice in delivered:
        grouped[(order.order_date, order.route_id)].append((order, invoice))

    # The most recent run is left open rather than done, so the app opens on
    # a van that still has something to do. Without it the demo lands on a
    # finished week and reads as an archive -- and on a Sunday, when the
    # history generates no trading at all, on nothing.
    run_count = 0
    days = sorted(grouped)
    latest = days[-1] if days else None
    for key in days:
        day, _route_id = key
        stops = grouped[key]
        live = key == latest
        run = Delivery(
            delivery_no=numbering.next_delivery_no(db, day),
            delivery_date=day,
            status="open" if live else "done",
            sent_at=None if live else dt.datetime.combine(day, dt.time(9, 0)),
            done_at=None if live else dt.datetime.combine(day, dt.time(19, 30)),
        )
        db.add(run)
        db.flush()
        for _order, invoice in stops:
            invoice.delivery_id = run.id
        run_count += 1
    db.flush()

    # --- today's orders, waiting for a van ------------------------------
    pending = _seed_pending_orders(db, today=today, rng=rng)

    return {
        "orders": len(delivered) + pending,
        "pending_orders": pending,
        "deliveries": run_count,
    }


def _seed_pending_orders(db: Session, *, today: dt.date, rng: random.Random) -> int:
    """Orders taken today for tomorrow's route, with no sheet built yet.

    Leaves the load-sheet screen with something real to work on.
    """
    tomorrow = today + dt.timedelta(days=1)
    route = db.execute(
        select(Route).where(Route.day_of_week == tomorrow.weekday()).limit(1)
    ).scalar_one_or_none()
    if route is None:
        return 0

    products = list(db.execute(select(Product).where(Product.is_active)).scalars())
    shops = list(
        db.execute(
            select(Retailer).where(Retailer.route_id == route.id, Retailer.is_active)
        ).scalars()
    )

    made = 0
    for retailer in shops:
        if rng.random() > 0.55:
            continue
        order = Order(
            order_no=numbering.next_order_no(db, today),
            retailer_id=retailer.id,
            route_id=route.id,
            order_date=today,
            requested_for=tomorrow,
            status="pending",
            note="Taken on the route, not yet loaded",
        )
        db.add(order)
        db.flush()

        value = Decimal("0.00")
        for product in rng.sample(products, k=rng.randint(3, 6)):
            cases = rng.randint(1, 3)
            qty = cases * product.pieces_per_case
            db.add(
                OrderLine(
                    order_id=order.id,
                    product_id=product.id,
                    cases=cases,
                    loose_pieces=0,
                    qty_pieces=qty,
                )
            )
            value += q2(Decimal(str(product.ptr)) * qty)
        order.estimated_value = q2(value)
        made += 1

    db.flush()
    return made


def seed_credit_notes(
    db: Session, *, invoices: list[Invoice], today: dt.date, rng: random.Random
) -> int:
    """A believable trickle of returns, damages and shortages."""
    candidates = [
        invoice
        for invoice in invoices
        if invoice.lines
        and today - dt.timedelta(days=75)
        <= invoice.invoice_date
        <= today - dt.timedelta(days=2)
    ]
    if not candidates:
        return 0

    reasons = ["return_saleable", "return_damaged", "near_expiry_return", "shortage"]
    weights = [0.42, 0.33, 0.15, 0.10]

    # Plan every note first, then issue them in date order. Document numbers
    # run with the calendar in a real book, and Table 13 of GSTR-1 reports a
    # from-to range, so numbers that jump around dates would read as gaps.
    planned = []
    for invoice in rng.sample(candidates, k=min(34, len(candidates))):
        chargeable = [line for line in invoice.lines if not line.is_free]
        if not chargeable:
            continue
        line = rng.choice(chargeable)
        per_case = line.product.pieces_per_case
        max_cases = line.qty_pieces // per_case
        if max_cases < 1:
            continue
        planned.append({
            "invoice": invoice,
            "line": line,
            "cases": rng.randint(1, min(2, max_cases)),
            "reason": rng.choices(reasons, weights=weights)[0],
            "note_date": min(
                invoice.invoice_date + dt.timedelta(days=rng.randint(2, 20)), today
            ),
        })

    made = 0
    for entry in sorted(planned, key=lambda e: (e["note_date"], e["invoice"].id)):
        invoice = entry["invoice"]
        line = entry["line"]
        reason = entry["reason"]
        note_date = entry["note_date"]
        try:
            credits.create_credit_note(
                db,
                invoice_id=invoice.id,
                reason=reason,
                lines=[
                    {
                        "invoice_line_id": line.id,
                        "cases": entry["cases"],
                        "loose_pieces": 0,
                    }
                ],
                note_date=note_date,
                note=CREDIT_NOTE_NARRATIVE[reason],
            )
            made += 1
        except credits.CreditNoteError:
            continue
    return made
