"""Stock as a derived quantity.

On-hand is always SUM(stock_ledger.qty_pieces), never a stored counter, so
every figure can be traced back to the movements that produced it.

Allocation is first-expiry-first-out rather than plain FIFO: with a 6-to-9
month shelf life the oldest *expiry* is what has to leave the godown first,
and batches already past expiry are excluded from sale entirely.

Stock has one place: the godown. Goods on a van have already been billed, so
they are no longer the firm's stock and there is nothing to keep track of out
there. An earlier version made a van a stock location; `models.Delivery`
records why that went.
"""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Product, StockBatch, StockLedger

# Buckets used for the near-expiry view, in days from the reference date.
EXPIRY_BUCKETS = ((0, "expired"), (30, "d30"), (60, "d60"), (90, "d90"))


def post_movement(
    db: Session,
    *,
    product_id: int,
    batch_id: int,
    qty_pieces: int,
    reason: str,
    occurred_on: dt.date,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
) -> StockLedger:
    """Append one movement. Positive quantities are inward, negative outward.

    A transfer is two calls, not one: negative at the place goods leave and
    positive where they arrive. Nothing here checks that the resulting balance
    is non-negative -- the caller allocates first, which is what establishes
    there is enough to move.
    """
    if qty_pieces == 0:
        raise ValueError("A stock movement cannot be zero pieces.")
    entry = StockLedger(
        product_id=product_id,
        batch_id=batch_id,
        qty_pieces=qty_pieces,
        reason=reason,
        occurred_on=occurred_on,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )
    db.add(entry)
    db.flush()
    return entry


def batch_balances(
    db: Session,
    product_id: int | None = None,
    as_of: dt.date | None = None,
) -> dict[int, int]:
    """Pieces on hand per batch id."""
    stmt = select(
        StockLedger.batch_id, func.coalesce(func.sum(StockLedger.qty_pieces), 0)
    ).group_by(StockLedger.batch_id)
    if product_id is not None:
        stmt = stmt.where(StockLedger.product_id == product_id)
    if as_of is not None:
        stmt = stmt.where(StockLedger.occurred_on <= as_of)
    return {batch_id: int(qty) for batch_id, qty in db.execute(stmt)}


def on_hand(
    db: Session,
    product_id: int,
    as_of: dt.date | None = None,
) -> int:
    """Pieces on hand for a product."""
    stmt = select(func.coalesce(func.sum(StockLedger.qty_pieces), 0)).where(
        StockLedger.product_id == product_id
    )
    if as_of is not None:
        stmt = stmt.where(StockLedger.occurred_on <= as_of)
    return int(db.execute(stmt).scalar_one())


class InsufficientStock(ValueError):
    """Raised when unexpired stock cannot cover a requested quantity."""

    def __init__(self, label: str, asked: int, available: int):
        self.label = label
        self.asked = asked
        self.available = available
        super().__init__(
            f"Not enough sellable stock for {label}: asked {asked} pieces, "
            f"{available} available before expiry."
        )


def plan_fefo(
    batches: list[StockBatch],
    balances: dict[int, int],
    qty_pieces: int,
    on_date: dt.date,
    label: str = "product",
) -> list[tuple[int, int]]:
    """Pure first-expiry-first-out planner.

    Takes batches and their balances as data so callers that already hold
    them in memory — the seeder, a bulk import — reuse this exact logic
    instead of reimplementing it.
    """
    if qty_pieces <= 0:
        raise ValueError("Allocation quantity must be positive.")

    ordered = sorted(batches, key=lambda b: (b.expiry_date, b.id))
    plan: list[tuple[int, int]] = []
    remaining = qty_pieces
    for batch in ordered:
        if remaining == 0:
            break
        available = balances.get(batch.id, 0)
        if available <= 0 or batch.expiry_date < on_date:
            continue
        take = min(available, remaining)
        plan.append((batch.id, take))
        remaining -= take

    if remaining > 0:
        sellable = sum(
            max(balances.get(b.id, 0), 0)
            for b in ordered
            if b.expiry_date >= on_date
        )
        raise InsufficientStock(label, qty_pieces, sellable)
    return plan


def first_inward_dates(
    db: Session, product_id: int | None = None
) -> dict[int, dt.date]:
    """When each batch first arrived.

    A batch cannot be sold before it was received, so an invoice dated earlier
    than the goods arrived must not be able to allocate from it.
    """
    stmt = (
        select(StockLedger.batch_id, func.min(StockLedger.occurred_on))
        .where(StockLedger.qty_pieces > 0)
        .group_by(StockLedger.batch_id)
    )
    if product_id is not None:
        stmt = stmt.where(StockLedger.product_id == product_id)
    return {batch_id: received for batch_id, received in db.execute(stmt)}


def allocate_fefo(
    db: Session,
    product_id: int,
    qty_pieces: int,
    on_date: dt.date,
) -> list[tuple[int, int]]:
    """Choose batches to satisfy a sale, first expiry first out.

    Returns a list of (batch_id, pieces). Raises InsufficientStock naming what
    is actually available, so the billing screen can say something useful
    instead of failing opaquely.

    Balances are taken as at the invoice date, and batches received after it
    are excluded, so back-dating a bill cannot consume stock that had not yet
    arrived. Reads only -- it reserves nothing. Callers that must not
    double-spend take a lock on the owning row before calling.
    """
    balances = batch_balances(db, product_id=product_id, as_of=on_date)
    received = first_inward_dates(db, product_id=product_id)
    batches = [
        batch
        for batch in db.execute(
            select(StockBatch).where(StockBatch.product_id == product_id)
        ).scalars()
        if received.get(batch.id) is not None and received[batch.id] <= on_date
    ]
    product = db.get(Product, product_id)
    label = product.display_name if product else f"product {product_id}"
    return plan_fefo(batches, balances, qty_pieces, on_date, label)


def sellable_pieces(db: Session, product_id: int, on_date: dt.date) -> int:
    """Pieces that could legitimately be sold on this date.

    Excludes anything already expired and anything not yet received, so the
    billing screen can warn before the biller commits to a quantity.
    """
    balances = batch_balances(db, product_id=product_id, as_of=on_date)
    received = first_inward_dates(db, product_id=product_id)
    total = 0
    for batch in db.execute(
        select(StockBatch).where(StockBatch.product_id == product_id)
    ).scalars():
        arrived = received.get(batch.id)
        if arrived is None or arrived > on_date or batch.expiry_date < on_date:
            continue
        total += max(balances.get(batch.id, 0), 0)
    return total


def stock_snapshot(db: Session, as_of: dt.date) -> list[dict]:
    """Per-product stock with value, cover days and expiry risk."""
    balances = batch_balances(db)
    batches = db.execute(select(StockBatch)).scalars().all()
    products = {
        p.id: p for p in db.execute(select(Product).where(Product.is_active)).scalars()
    }

    # Pieces sold over the last 30 days, to express stock as days of cover.
    thirty_days_ago = as_of - dt.timedelta(days=30)
    sold = dict(
        db.execute(
            select(
                StockLedger.product_id,
                func.coalesce(func.sum(-StockLedger.qty_pieces), 0),
            )
            .where(
                StockLedger.reason == "sale",
                StockLedger.occurred_on > thirty_days_ago,
                StockLedger.occurred_on <= as_of,
            )
            .group_by(StockLedger.product_id)
        ).all()
    )

    rows: dict[int, dict] = {}
    for batch in batches:
        qty = balances.get(batch.id, 0)
        if qty <= 0:
            continue
        product = products.get(batch.product_id)
        if product is None:
            continue
        row = rows.setdefault(
            product.id,
            {
                "product_id": product.id,
                "sku_code": product.sku_code,
                "brand": product.brand,
                "name": product.display_name,
                "pieces_per_case": product.pieces_per_case,
                "pieces": 0,
                "value": 0.0,
                "expired_pieces": 0,
                "near_expiry_pieces": 0,
                "near_expiry_value": 0.0,
                "earliest_expiry": None,
                "batches": [],
            },
        )
        value = float(batch.cost_per_piece) * qty
        row["pieces"] += qty
        row["value"] += value

        days_left = (batch.expiry_date - as_of).days
        if days_left < 0:
            row["expired_pieces"] += qty
        elif days_left <= 90:
            row["near_expiry_pieces"] += qty
            row["near_expiry_value"] += value

        if row["earliest_expiry"] is None or batch.expiry_date < row["earliest_expiry"]:
            row["earliest_expiry"] = batch.expiry_date
        row["batches"].append(
            {
                "batch_id": batch.id,
                "batch_no": batch.batch_no,
                "mfg_date": batch.mfg_date,
                "expiry_date": batch.expiry_date,
                "days_left": days_left,
                "pieces": qty,
                "cases": round(qty / product.pieces_per_case, 2),
            }
        )

    result = []
    for row in rows.values():
        per_case = row["pieces_per_case"]
        row["cases"] = round(row["pieces"] / per_case, 2)
        row["value"] = round(row["value"], 2)
        row["near_expiry_value"] = round(row["near_expiry_value"], 2)
        daily = sold.get(row["product_id"], 0) / 30
        row["daily_run_rate_pieces"] = round(daily, 2)
        row["cover_days"] = round(row["pieces"] / daily, 1) if daily > 0 else None
        row["batches"].sort(key=lambda b: b["expiry_date"])
        result.append(row)

    result.sort(key=lambda r: (r["brand"], r["name"]))
    return result
