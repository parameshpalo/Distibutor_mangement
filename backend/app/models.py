"""Schema for a biscuit distributor's operations.

Two deliberate choices run through this file:

1. Stock is never a mutable number. Every movement is an append-only row in
   `stock_ledger` with a signed quantity and a reason, so on-hand stock is
   always a SUM that can be explained line by line.
2. Payments attach to invoices through `payment_allocations`, not to the
   retailer as a running balance, so ageing buckets and credit checks stay
   truthful once part-payments begin.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .money import Money, Rate, q4

# --- enumerated string values (kept as plain text for portability) ----------

OUTLET_TYPES = (
    "kirana",
    "supermarket",
    "bakery",
    "pan_shop",
    "tea_stall",
    "canteen",
    "wholesale",
)
# Who the bill is raised on. A retailer buys at PTR; a sub-distributor
# buys at the lower PTD and resells onward.
PARTY_TYPES = ("retailer", "distributor")
# "inclusive" means the agreed rate already contains the tax, which is how
# an unregistered shop usually negotiates: one all-in price per case. The
# tax is backed out of it and reported exactly as on any other bill.
PRICE_MODES = ("exclusive", "inclusive")
STOCK_REASONS = (
    "opening",
    "grn",
    "sale",
    "sale_return_saleable",
    "sale_return_damaged",
    "damage",
    "expiry_writeoff",
    "adjustment",
)

# There is one place stock can be: the godown. A van is not a location,
# because goods on a van have already been billed and are no longer the
# firm's stock. An earlier design made the van a location so a trip could be
# reconciled at close; see `Delivery` for why that was dropped.
PAYMENT_MODES = ("cash", "upi", "cheque", "bank_transfer")
INVOICE_STATUSES = ("draft", "issued", "cancelled")

ORDER_STATUSES = ("pending", "on_load_sheet", "delivered", "cancelled")

# A van run, start to finish. Three words, because there is nothing else to
# say about it:
#   open  bills are still being added to it
#   out   the van has left with them
#   done  it is back
# No "loaded" stage: the goods are the bills, so a run is loaded the moment
# the bills are on it.
DELIVERY_STATUSES = ("open", "out", "done")

CREDIT_NOTE_REASONS = (
    "return_saleable",
    "return_damaged",
    "near_expiry_return",
    "shortage",
    "rate_difference",
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    """Render a portable SQL IN check for a CheckConstraint."""
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class CompanyProfile(Base):
    """The distributor's own details, printed on every tax invoice."""

    __tablename__ = "company_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    fssai_no: Mapped[str | None] = mapped_column(String(20))
    address_line1: Mapped[str] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state_name: Mapped[str] = mapped_column(String(100))
    state_code: Mapped[str] = mapped_column(String(2))
    pincode: Mapped[str] = mapped_column(String(6))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(120))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account: Mapped[str | None] = mapped_column(String(30))
    bank_ifsc: Mapped[str | None] = mapped_column(String(15))
    invoice_prefix: Mapped[str] = mapped_column(String(6), default="BD")


class GstRate(Base):
    """GST rate by HSN, dated.

    Rates are looked up against the invoice date, never stored on the product,
    so a reprint of an old invoice shows the rate that applied at the time.
    Biscuits (HSN 1905) changed slabs in the Sept-2025 rationalisation, which
    is exactly the case this table exists to survive.
    """

    __tablename__ = "gst_rates"
    __table_args__ = (Index("ix_gst_rates_lookup", "hsn", "effective_from"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hsn: Mapped[str] = mapped_column(String(8))
    rate: Mapped[object] = mapped_column(Rate)  # percent, e.g. 5.0000
    effective_from: Mapped[dt.date] = mapped_column(Date)
    effective_to: Mapped[dt.date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200))


class NumberSeries(Base):
    """Gapless per-financial-year counters for documents."""

    __tablename__ = "number_series"
    __table_args__ = (UniqueConstraint("kind", "fy", name="uq_series_kind_fy"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # invoice | grn | receipt
    fy: Mapped[str] = mapped_column(String(5))  # e.g. 26-27
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class Route(Base):
    """A route of retailers visited on a fixed weekday."""

    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    day_of_week: Mapped[int] = mapped_column(Integer)  # 0 = Monday

    retailers: Mapped[list[Retailer]] = relationship(back_populates="route")


class Product(Base):
    """One sellable SKU.

    Biscuits move in cases, so `pieces_per_case` is load-bearing: stock,
    invoices and targets all convert through it. Prices are per piece and
    exclusive of GST, which is how PTD and PTR are quoted in the trade.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(30), unique=True)
    brand: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(160))
    pack_size_g: Mapped[int] = mapped_column(Integer)
    pieces_per_case: Mapped[int] = mapped_column(Integer)
    hsn: Mapped[str] = mapped_column(String(8), default="1905")
    mrp: Mapped[object] = mapped_column(Money)  # consumer price, incl. GST
    ptr: Mapped[object] = mapped_column(Rate)  # price to retailer, pre-GST
    ptd: Mapped[object] = mapped_column(Rate)  # price to distributor, pre-GST
    # What the company charges him per piece, pre-GST and before scheme, off
    # its own order sheet. This is his cost, not a selling price, and it is
    # what makes the margin on a bill a real number rather than a guess.
    landing_rate: Mapped[object] = mapped_column(Rate, default=0)
    # The purchase scheme the company allows him on this SKU. It reduces what
    # he effectively pays; it is not a discount he gives a shop.
    purchase_scheme_pct: Mapped[object] = mapped_column(Rate, default=0)
    # Standing trade discount, pre-filled on every bill line and overridable
    # there. A scheme the owner runs all year lives here rather than being
    # retyped on each bill.
    default_discount_pct: Mapped[object] = mapped_column(Rate, default=0)
    shelf_life_days: Mapped[int] = mapped_column(Integer, default=240)
    case_weight_kg: Mapped[object] = mapped_column(Rate, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def display_name(self) -> str:
        """What the bill prints.

        The company's own SKU names are already self-describing -- "Cream Bites
        Litchi", "Hamara Crackers" -- so the brand group is a filing label, not
        part of the name. Repeating it gave "Crackers Hamara Crackers".
        """
        return f"{self.name} {self.pack_size_g}g"

    @property
    def effective_cost(self) -> object:
        """His real cost per piece: the landing rate less the purchase scheme."""
        landing = Decimal(str(self.landing_rate or 0))
        scheme = Decimal(str(self.purchase_scheme_pct or 0))
        return q4(landing * (Decimal(100) - scheme) / Decimal(100))


class Retailer(Base):
    """A party the distributor bills: a shop, or a sub-distributor.

    Named for the common case, but `party_type` decides how it is priced.
    `gstin` is nullable throughout: most kirana shops are below the
    registration threshold, and a bill to one is an ordinary B2C supply.
    """

    __tablename__ = "retailers"
    __table_args__ = (
        CheckConstraint(_in_clause("party_type", PARTY_TYPES), name="ck_party_type"),
        CheckConstraint(_in_clause("price_mode", PRICE_MODES), name="ck_party_price_mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    shop_name: Mapped[str] = mapped_column(String(160))
    owner_name: Mapped[str | None] = mapped_column(String(120))
    gstin: Mapped[str | None] = mapped_column(String(15))
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    # Who is buying. A retailer is billed at PTR, a sub-distributor at the
    # lower PTD. This is the buyer's type, not the seller's.
    party_type: Mapped[str] = mapped_column(String(20), default="retailer")
    # How this party's rate is quoted. "inclusive" means the agreed rate
    # already contains GST and the tax is backed out of it; the supply is
    # taxed and reported either way.
    price_mode: Mapped[str] = mapped_column(String(12), default="exclusive")
    phone: Mapped[str | None] = mapped_column(String(20))
    address_line: Mapped[str | None] = mapped_column(String(250))
    city: Mapped[str | None] = mapped_column(String(100))
    state_name: Mapped[str] = mapped_column(String(100), default="Telangana")
    state_code: Mapped[str] = mapped_column(String(2), default="36")
    pincode: Mapped[str | None] = mapped_column(String(6))
    outlet_type: Mapped[str] = mapped_column(String(20), default="kirana")
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id"))
    credit_limit: Mapped[object] = mapped_column(Money, default=0)
    credit_days: Mapped[int] = mapped_column(Integer, default=7)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_on: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)

    route: Mapped[Route | None] = relationship(back_populates="retailers")


class StockBatch(Base):
    """A manufacturing batch of one product, with its own expiry."""

    __tablename__ = "stock_batches"
    __table_args__ = (
        UniqueConstraint("product_id", "batch_no", name="uq_batch_product_no"),
        Index("ix_batch_fefo", "product_id", "expiry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_no: Mapped[str] = mapped_column(String(40))
    mfg_date: Mapped[dt.date] = mapped_column(Date)
    expiry_date: Mapped[dt.date] = mapped_column(Date)
    cost_per_piece: Mapped[object] = mapped_column(Rate)

    product: Mapped[Product] = relationship()


class StockLedger(Base):
    """Append-only record of every stock movement.

    Nothing here is ever updated or deleted; a correction is another row.
    On-hand stock for a batch at a place is SUM(qty_pieces) over its rows there.

    `location` is what makes a van tractable. A batch can sit in the godown and
    on two vans at once, so the place belongs on the movement, not on the batch
    -- one manufacturing lot stays one row in `stock_batches`, which is what
    keeps the invoice-line batch trail intact for credit notes.
    """

    __tablename__ = "stock_ledger"
    __table_args__ = (
        Index("ix_ledger_product_date", "product_id", "occurred_on"),
        Index("ix_ledger_batch", "batch_id"),
        CheckConstraint(_in_clause("reason", STOCK_REASONS), name="ck_ledger_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"))
    qty_pieces: Mapped[int] = mapped_column(Integer)  # signed: + in, - out
    reason: Mapped[str] = mapped_column(String(30))
    ref_type: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    occurred_on: Mapped[dt.date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    product: Mapped[Product] = relationship()
    batch: Mapped[StockBatch] = relationship()


class Purchase(Base):
    """Goods received from the company or its depot (a GRN)."""

    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    grn_no: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_name: Mapped[str] = mapped_column(String(160))
    company_invoice_no: Mapped[str] = mapped_column(String(40))
    company_invoice_date: Mapped[dt.date] = mapped_column(Date)
    received_on: Mapped[dt.date] = mapped_column(Date)
    taxable_total: Mapped[object] = mapped_column(Money, default=0)
    tax_total: Mapped[object] = mapped_column(Money, default=0)
    grand_total: Mapped[object] = mapped_column(Money, default=0)
    note: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list[PurchaseLine]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan"
    )


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"))
    cases: Mapped[int] = mapped_column(Integer, default=0)
    loose_pieces: Mapped[int] = mapped_column(Integer, default=0)
    qty_pieces: Mapped[int] = mapped_column(Integer)
    rate_per_piece: Mapped[object] = mapped_column(Rate)
    taxable: Mapped[object] = mapped_column(Money)
    gst_rate: Mapped[object] = mapped_column(Rate)
    tax_amount: Mapped[object] = mapped_column(Money)
    line_total: Mapped[object] = mapped_column(Money)

    purchase: Mapped[Purchase] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    batch: Mapped[StockBatch] = relationship()


class Invoice(Base):
    """A GST tax invoice raised on a retailer."""

    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoice_retailer_date", "retailer_id", "invoice_date"),
        Index("ix_invoice_date", "invoice_date"),
        CheckConstraint(_in_clause("status", INVOICE_STATUSES), name="ck_invoice_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(16), unique=True)
    invoice_date: Mapped[dt.date] = mapped_column(Date)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"))
    # Set when the bill came from a pre-taken order rather than being keyed in.
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    place_of_supply: Mapped[str] = mapped_column(String(2))
    is_interstate: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[dt.date] = mapped_column(Date)
    # How the rates were quoted when this bill was raised. Recorded on the
    # invoice, not read from the party, so a reprint shows what was agreed.
    price_mode: Mapped[str] = mapped_column(String(12), default="exclusive")

    taxable_total: Mapped[object] = mapped_column(Money, default=0)
    discount_total: Mapped[object] = mapped_column(Money, default=0)
    cgst_total: Mapped[object] = mapped_column(Money, default=0)
    sgst_total: Mapped[object] = mapped_column(Money, default=0)
    igst_total: Mapped[object] = mapped_column(Money, default=0)
    round_off: Mapped[object] = mapped_column(Money, default=0)
    grand_total: Mapped[object] = mapped_column(Money, default=0)

    status: Mapped[str] = mapped_column(String(12), default="issued")
    note: Mapped[str | None] = mapped_column(Text)

    # How the goods leave. Null is a solo bill: the buyer takes it away in
    # his own vehicle. Set means the owner is delivering it, and this is the
    # van run it travels on. One nullable column is the whole of the change
    # that replaced the beat.
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("deliveries.id"))

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    retailer: Mapped[Retailer] = relationship()
    delivery: Mapped["Delivery | None"] = relationship(back_populates="bills")
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    allocations: Mapped[list[PaymentAllocation]] = relationship(back_populates="invoice")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    hsn: Mapped[str] = mapped_column(String(8))
    cases: Mapped[int] = mapped_column(Integer, default=0)
    loose_pieces: Mapped[int] = mapped_column(Integer, default=0)
    qty_pieces: Mapped[int] = mapped_column(Integer)
    rate_per_piece: Mapped[object] = mapped_column(Rate)
    # The all-in rate agreed with the buyer, when the bill was quoted
    # inclusive of GST. Null on an ordinary exclusive bill, where
    # `rate_per_piece` is already the agreed figure.
    quoted_rate_per_piece: Mapped[object | None] = mapped_column(Rate)
    gross: Mapped[object] = mapped_column(Money)
    discount: Mapped[object] = mapped_column(Money, default=0)
    taxable: Mapped[object] = mapped_column(Money)
    gst_rate: Mapped[object] = mapped_column(Rate)
    cgst: Mapped[object] = mapped_column(Money, default=0)
    sgst: Mapped[object] = mapped_column(Money, default=0)
    igst: Mapped[object] = mapped_column(Money, default=0)
    line_total: Mapped[object] = mapped_column(Money)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    batch_allocations: Mapped[list[InvoiceLineBatch]] = relationship(
        back_populates="line", cascade="all, delete-orphan"
    )


class InvoiceLineBatch(Base):
    """Which batches satisfied a sold line, chosen first-expiry-first-out."""

    __tablename__ = "invoice_line_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("invoice_lines.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"))
    qty_pieces: Mapped[int] = mapped_column(Integer)

    line: Mapped[InvoiceLine] = relationship(back_populates="batch_allocations")
    batch: Mapped[StockBatch] = relationship()


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(_in_clause("mode", PAYMENT_MODES), name="ck_payment_mode"),
        Index("ix_payment_retailer_date", "retailer_id", "payment_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(20), unique=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"))
    payment_date: Mapped[dt.date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(20))
    amount: Mapped[object] = mapped_column(Money)
    reference: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(Text)

    retailer: Mapped[Retailer] = relationship()
    allocations: Mapped[list[PaymentAllocation]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )


class PaymentAllocation(Base):
    """Ties a slice of a payment to one invoice."""

    __tablename__ = "payment_allocations"
    __table_args__ = (Index("ix_alloc_invoice", "invoice_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    amount: Mapped[object] = mapped_column(Money)

    payment: Mapped[Payment] = relationship(back_populates="allocations")
    invoice: Mapped[Invoice] = relationship(back_populates="allocations")


# --- orders ---------------------------------------------------------------


class Order(Base):
    """What a retailer asked for at the shop, before anything is billed.

    An order is a promise, not a document of record: it moves no stock and
    charges no tax. Stock moves and GST applies only when it becomes an
    invoice on delivery.
    """

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_order_date", "order_date"),
        Index("ix_order_status", "status"),
        CheckConstraint(_in_clause("status", ORDER_STATUSES), name="ck_order_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(20), unique=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"))
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id"))
    order_date: Mapped[dt.date] = mapped_column(Date)
    requested_for: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # Indicative only: the real figure is struck when the invoice is raised.
    estimated_value: Mapped[object] = mapped_column(Money, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    retailer: Mapped[Retailer] = relationship()
    route: Mapped[Route | None] = relationship()
    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    cases: Mapped[int] = mapped_column(Integer, default=0)
    loose_pieces: Mapped[int] = mapped_column(Integer, default=0)
    qty_pieces: Mapped[int] = mapped_column(Integer)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)

    order: Mapped[Order] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


# --- the delivery: a van carrying bills already raised ---------------------


class Delivery(Base):
    """One van going out with bills on it.

    This is deliberately thin. It is not a plan, it is not a stock location
    and it holds no quantities of its own: it is a *label on bills*, and
    nothing else. Everything the van is carrying is the sum of the lines on
    the bills attached to it, derived on read.

    The reason it is thin is that a bill is the real event. Raising one
    issues the invoice number, moves the stock out of the godown and creates
    the receivable, whether the shop collects the goods itself or the owner
    drives them over. So by the time a van is loaded, the goods on it have
    already been sold, and there is no second movement to record and no van
    balance to reconcile.

    What that costs is worth stating where someone will read it: goods that
    go missing off a van do not show up as a shortage that evening. They show
    up at the next stock count, as a difference nobody can attribute. An
    earlier design tracked the van as a stock location so it could be
    reconciled daily; it was removed because it made the owner plan a trip
    before he could bill anyone, which is not the order the work happens in.
    """

    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_delivery_date", "delivery_date"),
        Index("ix_delivery_status", "status"),
        CheckConstraint(
            _in_clause("status", DELIVERY_STATUSES), name="ck_delivery_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_no: Mapped[str] = mapped_column(String(20), unique=True)
    delivery_date: Mapped[dt.date] = mapped_column(Date)
    # No vehicle and no driver. A firm this size has one or two vans and the
    # owner knows which went where; asking for it on every bill bought
    # nothing and cost two fields of typing at the counter.
    status: Mapped[str] = mapped_column(String(12), default="open")
    note: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    bills: Mapped[list[Invoice]] = relationship(
        back_populates="delivery", order_by="Invoice.id"
    )


class CreditNote(Base):
    """A credit note against an invoice: returns, shortages, rate differences.

    Carries its own GST reversal at the rate the original invoice used, and
    reduces what the retailer owes. Saleable returns go back into stock
    against the batch they left on; damaged ones never re-enter saleable
    stock and are written off instead.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        Index("ix_cn_date", "note_date"),
        CheckConstraint(_in_clause("reason", CREDIT_NOTE_REASONS), name="ck_cn_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    note_no: Mapped[str] = mapped_column(String(16), unique=True)
    note_date: Mapped[dt.date] = mapped_column(Date)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"))
    reason: Mapped[str] = mapped_column(String(24))
    is_interstate: Mapped[bool] = mapped_column(Boolean, default=False)
    place_of_supply: Mapped[str] = mapped_column(String(2))

    taxable_total: Mapped[object] = mapped_column(Money, default=0)
    cgst_total: Mapped[object] = mapped_column(Money, default=0)
    sgst_total: Mapped[object] = mapped_column(Money, default=0)
    igst_total: Mapped[object] = mapped_column(Money, default=0)
    round_off: Mapped[object] = mapped_column(Money, default=0)
    grand_total: Mapped[object] = mapped_column(Money, default=0)

    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    invoice: Mapped[Invoice] = relationship()
    retailer: Mapped[Retailer] = relationship()
    lines: Mapped[list[CreditNoteLine]] = relationship(
        back_populates="credit_note", cascade="all, delete-orphan"
    )


class CreditNoteLine(Base):
    __tablename__ = "credit_note_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("credit_notes.id"))
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("invoice_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    hsn: Mapped[str] = mapped_column(String(8))
    cases: Mapped[int] = mapped_column(Integer, default=0)
    loose_pieces: Mapped[int] = mapped_column(Integer, default=0)
    qty_pieces: Mapped[int] = mapped_column(Integer)
    restock: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_per_piece: Mapped[object] = mapped_column(Rate)
    taxable: Mapped[object] = mapped_column(Money)
    gst_rate: Mapped[object] = mapped_column(Rate)
    cgst: Mapped[object] = mapped_column(Money, default=0)
    sgst: Mapped[object] = mapped_column(Money, default=0)
    igst: Mapped[object] = mapped_column(Money, default=0)
    line_total: Mapped[object] = mapped_column(Money)

    credit_note: Mapped[CreditNote] = relationship(back_populates="lines")
    invoice_line: Mapped[InvoiceLine] = relationship()
    product: Mapped[Product] = relationship()
