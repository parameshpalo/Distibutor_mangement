"""Today: what needs doing, and how the month is going.

This is deliberately not a management dashboard. It answers two questions and
stops: *what needs my attention right now*, and *am I selling more or less than
before*. There are no targets, because the business does not run against a
plan; no per-salesman table, because the person with the van is a name on a
route, not a tracked employee; and no call statistics, because nobody logs calls.

Sales are reported on taxable (pre-GST) value, which is the figure the trade
quotes and compares. Cases are shown beside the rupees because stock, orders
and loading are all counted in cases.
"""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Delivery,
    CreditNote,
    Invoice,
    InvoiceLine,
    Order,
    Payment,
    Product,
    Retailer,
    StockLedger,
)
from ..money import ZERO, q2
from ..services import deliveries, receivables, stock

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

#: "Near expiry" on this page means sooner than this. The stock page uses a
#: wider 90-day window for planning; what belongs on Today is the stock that
#: has to move this month or be written off.
NEAR_EXPIRY_DAYS = 30

#: A SKU with stock but fewer than this many cases sold in the month is shown
#: as not moving. Low enough that it means "sitting there", not "selling slowly".
SLOW_MOVER_CASES = 10


def month_window(day: dt.date) -> tuple[dt.date, dt.date]:
    start = day.replace(day=1)
    end = (start.replace(year=start.year + (start.month == 12),
                         month=(start.month % 12) + 1) - dt.timedelta(days=1))
    return start, end


def quarter_window(day: dt.date) -> tuple[dt.date, dt.date]:
    first_month = 3 * ((day.month - 1) // 3) + 1
    start = dt.date(day.year, first_month, 1)
    last_month = first_month + 2
    end = (dt.date(day.year + (last_month == 12), (last_month % 12) + 1, 1)
           - dt.timedelta(days=1))
    return start, end


def _sales_value(db: Session, start: dt.date, end: dt.date) -> Decimal:
    total = db.execute(
        select(func.coalesce(func.sum(Invoice.taxable_total), 0)).where(
            Invoice.status == "issued",
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
        )
    ).scalar_one()
    return q2(total or 0)


def _sales_cases(db: Session, start: dt.date, end: dt.date) -> float:
    total = db.execute(
        select(
            func.coalesce(
                func.sum(cast(InvoiceLine.qty_pieces, Float) / Product.pieces_per_case),
                0.0,
            )
        )
        .select_from(InvoiceLine)
        .join(Product, Product.id == InvoiceLine.product_id)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(
            Invoice.status == "issued",
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
        )
    ).scalar_one()
    return round(float(total or 0), 1)


def _period(db: Session, label: str, start: dt.date, end: dt.date) -> dict:
    """One period's sales, in rupees and cases. No target, no pace."""
    return {
        "label": label,
        "period_start": start,
        "period_end": end,
        "value": float(_sales_value(db, start, end)),
        "cases": _sales_cases(db, start, end),
    }


def _cases_by_product(db: Session, start: dt.date, end: dt.date) -> dict[int, float]:
    return {
        pid: round(float(cases or 0), 1)
        for pid, cases in db.execute(
            select(
                InvoiceLine.product_id,
                func.sum(
                    cast(InvoiceLine.qty_pieces, Float) / Product.pieces_per_case
                ),
            )
            .select_from(InvoiceLine)
            .join(Product, Product.id == InvoiceLine.product_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                Invoice.status == "issued",
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
            .group_by(InvoiceLine.product_id)
        ).all()
    }


def _value_by_product(db: Session, start: dt.date, end: dt.date) -> dict[int, Decimal]:
    return {
        pid: q2(val or 0)
        for pid, val in db.execute(
            select(InvoiceLine.product_id, func.sum(InvoiceLine.taxable))
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                Invoice.status == "issued",
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
            .group_by(InvoiceLine.product_id)
        ).all()
    }


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    today = dt.date.today()
    month_start, month_end = month_window(today)
    quarter_start, quarter_end = quarter_window(today)

    # --- today -------------------------------------------------------------
    today_invoices = db.execute(
        select(Invoice).where(
            Invoice.status == "issued", Invoice.invoice_date == today
        )
    ).scalars().all()
    today_collected = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.payment_date == today
        )
    ).scalar_one()

    # --- stock -------------------------------------------------------------
    snapshot = stock.stock_snapshot(db, today)
    in_stock_ids = {row["product_id"] for row in snapshot}
    active_products = db.execute(
        select(Product.id, Product.sku_code, Product.name, Product.pack_size_g)
        .where(Product.is_active)
    ).all()
    out_of_stock = [
        {"product_id": pid, "sku_code": sku, "name": f"{name} {pack}g"}
        for pid, sku, name, pack in active_products
        if pid not in in_stock_ids
    ]

    # Near expiry on the Today page is the 30-day window, recomputed from the
    # batch rows rather than reusing the snapshot's wider 90-day figure.
    near_expiry = []
    for row in snapshot:
        soon = [b for b in row["batches"] if 0 <= b["days_left"] <= NEAR_EXPIRY_DAYS]
        if not soon:
            continue
        pieces = sum(b["pieces"] for b in soon)
        near_expiry.append({
            "product_id": row["product_id"],
            "sku_code": row["sku_code"],
            "name": row["name"],
            "pieces": pieces,
            "cases": round(pieces / row["pieces_per_case"], 2),
            # Valued at cost: this is what is at risk of being written off,
            # not what it would have fetched. The snapshot's batch rows carry
            # no cost, so this uses the product's average cost on hand — close
            # enough for a warning, and never quoted as a ledger figure.
            "value": round(
                pieces * (row["value"] / row["pieces"] if row["pieces"] else 0), 2
            ),
            "earliest_expiry": min(b["expiry_date"] for b in soon),
            "days_left": min(b["days_left"] for b in soon),
        })
    near_expiry.sort(key=lambda r: r["days_left"])

    low_cover = sorted(
        (s for s in snapshot if s["cover_days"] is not None and s["cover_days"] < 10),
        key=lambda s: s["cover_days"],
    )[:8]

    # --- moving and not moving, this month --------------------------------
    month_cases = _cases_by_product(db, month_start, month_end)
    month_value = _value_by_product(db, month_start, month_end)
    prev_end = month_start - dt.timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    last_value = _value_by_product(db, prev_start, prev_end)

    moving = []
    for product_id, value in month_value.items():
        product = db.get(Product, product_id)
        before = last_value.get(product_id, ZERO)
        moving.append({
            "product_id": product_id,
            "name": product.display_name if product else str(product_id),
            "brand": product.brand if product else None,
            "cases": month_cases.get(product_id, 0.0),
            "value": float(value),
            "previous": float(before),
            "change_pct": (
                round(float((value - before) / before * 100), 1) if before > 0 else None
            ),
        })
    top_movers = sorted(moving, key=lambda m: -m["cases"])[:8]

    # Not moving: stock sitting in the godown that the month barely touched.
    # Built from the snapshot, not from sales, so a SKU with no sales at all
    # still shows up — which is the case worth seeing.
    #
    # Ranked by the value sitting there, not by how little sold. Sorting by
    # sales first put a two-case remnant above ₹40,000 of dead stock, which is
    # the opposite of useful: the question this answers is "where is my money
    # stuck", so the money leads.
    slow_movers = sorted(
        (
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "cases_on_hand": row["cases"],
                "cases_sold": month_cases.get(row["product_id"], 0.0),
                "value": row["value"],
            }
            for row in snapshot
            if month_cases.get(row["product_id"], 0.0) < SLOW_MOVER_CASES
        ),
        key=lambda r: -r["value"],
    )[:8]

    # --- six-month trend ---------------------------------------------------
    trend = []
    cursor = month_start
    for _ in range(6):
        cursor = (cursor - dt.timedelta(days=1)).replace(day=1)
    for _ in range(7):
        start, end = month_window(cursor)
        trend.append({
            "month": f"{start:%b %Y}",
            "month_start": start,
            "value": float(_sales_value(db, start, end)),
            "cases": _sales_cases(db, start, end),
        })
        cursor = end + dt.timedelta(days=1)

    # Drop leading months from before the business started billing here, so
    # the chart does not open on a meaningless zero.
    while len(trend) > 1 and trend[0]["value"] == 0:
        trend.pop(0)

    # --- orders waiting to be billed --------------------------------------
    pending_orders = db.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.estimated_value), 0),
        ).where(Order.status.in_(["pending", "on_load_sheet"]))
    ).one()

    # --- returns and damage this month --------------------------------
    credited = db.execute(
        select(
            func.count(CreditNote.id),
            func.coalesce(func.sum(CreditNote.grand_total), 0),
        ).where(
            CreditNote.note_date >= month_start, CreditNote.note_date <= month_end
        )
    ).one()
    damaged_pieces = db.execute(
        select(func.coalesce(func.sum(-StockLedger.qty_pieces), 0)).where(
            StockLedger.reason == "damage",
            StockLedger.occurred_on >= month_start,
            StockLedger.occurred_on <= month_end,
        )
    ).scalar_one()

    # Overdue is everything that is not in the "current" bucket: a bill is
    # either still within its credit days or it is late. Computed here rather
    # than on the page so one definition serves every screen.
    ageing = receivables.ageing_report(db, today)
    overdue = round(
        sum(b["amount"] for b in ageing["buckets"] if b["label"] != "current"), 2
    )
    overdue_count = sum(
        b["count"] for b in ageing["buckets"] if b["label"] != "current"
    )

    # --- vans --------------------------------------------------------------
    #
    # A van run is a set of bills, so everything here is a sum over them.
    # "To deliver" is the money already billed and not yet handed over,
    # which is the one figure about a van the owner acts on in the morning.
    runs_today = list(db.execute(
        select(Delivery)
        .where(Delivery.status != "done", Delivery.delivery_date <= today)
        .order_by(Delivery.delivery_date, Delivery.id)
    ).scalars())
    vans_now = []
    for run in runs_today:
        summary = deliveries.run_summary(db, run)
        vans_now.append({
            "id": run.id,
            "delivery_no": run.delivery_no,
            "delivery_date": run.delivery_date,
            "label": run.delivery_no,
            "status": run.status,
            "bill_count": summary["bill_count"],
            "shop_count": summary["shop_count"],
            "value": summary["value"],
            "total_cases": summary["total_cases"],
        })

    # Runs still open with nothing on them. An empty run left over from
    # yesterday is almost always a half-finished thought, and saying so is
    # cheaper than letting it sit there looking like work in progress.
    empty_open = [v for v in vans_now if v["status"] == "open" and not v["bill_count"]]

    vans = {
        "runs": vans_now,
        "out_count": sum(1 for v in vans_now if v["status"] == "out"),
        "open_count": sum(1 for v in vans_now if v["status"] == "open"),
        "to_deliver": round(
            sum(v["value"] for v in vans_now if v["status"] == "out"), 2
        ),
        "shops_to_reach": sum(
            v["shop_count"] for v in vans_now if v["status"] == "out"
        ),
        "empty_open": empty_open[:4],
    }

    return {
        "as_of": today,
        "today": {
            "invoices": len(today_invoices),
            "value": float(q2(sum((q2(i.taxable_total) for i in today_invoices), ZERO))),
            "collected": float(q2(today_collected or 0)),
            "retailers_billed": len({i.retailer_id for i in today_invoices}),
        },
        "month": _period(db, f"{month_start:%B}", month_start, month_end),
        "quarter": _period(
            db,
            f"Q{(quarter_start.month - 1) // 3 + 1}",
            quarter_start,
            quarter_end,
        ),
        "trend": trend,
        "receivables": {
            **ageing,
            "overdue": overdue,
            "overdue_count": overdue_count,
        },
        "stock": {
            "skus_in_stock": len(snapshot),
            "value": round(sum(s["value"] for s in snapshot), 2),
            "near_expiry_count": len(near_expiry),
            "near_expiry_value": round(sum(r["value"] for r in near_expiry), 2),
            "near_expiry": near_expiry[:8],
            "expired_pieces": sum(s["expired_pieces"] for s in snapshot),
            "out_of_stock_count": len(out_of_stock),
            "out_of_stock": out_of_stock[:8],
            "low_cover": low_cover,
        },
        "orders": {
            "pending": pending_orders[0] or 0,
            "pending_value": float(q2(pending_orders[1] or 0)),
        },
        "vans": vans,
        "returns": {
            "credit_notes": credited[0] or 0,
            "credited_value": float(q2(credited[1] or 0)),
            "damaged_pieces": int(damaged_pieces or 0),
        },
        "top_movers": top_movers,
        "slow_movers": slow_movers,
        # Sent so the page can say what "not moving" means without hardcoding
        # a number that would then drift from this one.
        "slow_mover_cases": SLOW_MOVER_CASES,
        "retailers": {
            "active": db.execute(
                select(func.count(Retailer.id)).where(Retailer.is_active)
            ).scalar_one(),
        },
    }
