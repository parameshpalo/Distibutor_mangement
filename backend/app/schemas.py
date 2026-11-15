"""Request and response shapes.

Money crosses the wire as a JSON number rounded to paise. Every calculation
stays server-side in Decimal; the client only formats what it is given, so
no rupee arithmetic ever happens in JavaScript.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from .models import PARTY_TYPES, PRICE_MODES


def money(value) -> float:
    """Render an exact Decimal as a JSON-friendly number."""
    return float(Decimal(str(value or 0)))


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- masters ---------------------------------------------------------------


class CompanyOut(ApiModel):
    legal_name: str
    trade_name: str
    gstin: str
    pan: str | None = None
    fssai_no: str | None = None
    address_line1: str
    address_line2: str | None = None
    city: str
    state_name: str
    state_code: str
    pincode: str
    phone: str | None = None
    email: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    bank_ifsc: str | None = None
    invoice_prefix: str


class CompanyIn(BaseModel):
    """Changes to the firm's own details.

    Every field is optional: the My firm page saves what was edited and leaves
    the rest alone, so a half-filled profile can be completed a bit at a time
    as the papers are found. `state_code` is not accepted -- it is the first
    two characters of the GSTIN, which is the rule the portal applies, and
    letting the two disagree would put the wrong place of supply on bills.
    """

    legal_name: str | None = None
    trade_name: str | None = None
    gstin: str | None = Field(default=None, min_length=15, max_length=15)
    pan: str | None = None
    fssai_no: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state_name: str | None = None
    pincode: str | None = Field(default=None, min_length=6, max_length=6)
    phone: str | None = None
    email: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    bank_ifsc: str | None = None
    invoice_prefix: str | None = Field(default=None, min_length=1, max_length=6)


class ProductOut(ApiModel):
    id: int
    sku_code: str
    brand: str
    name: str
    pack_size_g: int
    pieces_per_case: int
    hsn: str
    mrp: Decimal
    ptr: Decimal
    ptd: Decimal
    landing_rate: Decimal = Decimal("0")
    purchase_scheme_pct: Decimal = Decimal("0")
    default_discount_pct: Decimal = Decimal("0")
    shelf_life_days: int
    is_active: bool

    @field_serializer(
        "mrp",
        "ptr",
        "ptd",
        "landing_rate",
        "purchase_scheme_pct",
        "default_discount_pct",
    )
    def _ser(self, value: Decimal) -> float:
        return money(value)


class ProductIn(BaseModel):
    sku_code: str = Field(min_length=2, max_length=30)
    brand: str
    name: str
    pack_size_g: int = Field(gt=0)
    pieces_per_case: int = Field(gt=0)
    hsn: str = "1905"
    mrp: Decimal = Field(gt=0)
    ptr: Decimal = Field(gt=0)
    ptd: Decimal = Field(gt=0)
    # What he pays the company, per piece and pre-GST, with the purchase
    # scheme it allows him. Optional: a SKU he sources elsewhere has neither.
    landing_rate: Decimal = Field(default=Decimal("0"), ge=0)
    purchase_scheme_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    default_discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    shelf_life_days: int = Field(default=240, gt=0)


class ProductPatch(BaseModel):
    """Every field optional: only what is sent is changed.

    `sku_code` is deliberately absent. Invoices already printed quote it,
    so renaming one after the fact would make old bills unmatchable.
    """

    brand: str | None = None
    name: str | None = None
    pack_size_g: int | None = Field(default=None, gt=0)
    pieces_per_case: int | None = Field(default=None, gt=0)
    hsn: str | None = None
    mrp: Decimal | None = Field(default=None, gt=0)
    ptr: Decimal | None = Field(default=None, gt=0)
    ptd: Decimal | None = Field(default=None, gt=0)
    landing_rate: Decimal | None = Field(default=None, ge=0)
    purchase_scheme_pct: Decimal | None = Field(default=None, ge=0, le=100)
    default_discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    shelf_life_days: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class RouteOut(ApiModel):
    id: int
    name: str
    day_of_week: int
    retailer_count: int = 0


class RetailerOut(ApiModel):
    id: int
    code: str
    shop_name: str
    owner_name: str | None = None
    gstin: str | None = None
    is_registered: bool
    party_type: str = "retailer"
    price_mode: str = "exclusive"
    phone: str | None = None
    address_line: str | None = None
    city: str | None = None
    state_name: str
    state_code: str
    outlet_type: str
    route_id: int | None = None
    route_name: str | None = None
    credit_limit: Decimal
    credit_days: int
    is_active: bool

    @field_serializer("credit_limit")
    def _ser(self, value: Decimal) -> float:
        return money(value)


class RetailerIn(BaseModel):
    shop_name: str = Field(min_length=2)
    owner_name: str | None = None
    gstin: str | None = None
    party_type: str = "retailer"
    price_mode: str = "exclusive"
    phone: str | None = None
    address_line: str | None = None
    city: str | None = None
    state_name: str = "Telangana"
    state_code: str = "36"
    pincode: str | None = None
    outlet_type: str = "kirana"
    route_id: int | None = None
    credit_limit: Decimal = Decimal("0")
    credit_days: int = 7

    @field_validator("gstin")
    @classmethod
    def _check_gstin(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        value = value.strip().upper()
        if len(value) != 15:
            raise ValueError("A GSTIN is exactly 15 characters.")
        return value

    @field_validator("party_type")
    @classmethod
    def _check_party_type(cls, value: str | None) -> str | None:
        if value is not None and value not in PARTY_TYPES:
            raise ValueError(f"party_type must be one of {', '.join(PARTY_TYPES)}.")
        return value

    @field_validator("price_mode")
    @classmethod
    def _check_price_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in PRICE_MODES:
            raise ValueError(f"price_mode must be one of {', '.join(PRICE_MODES)}.")
        return value


class RetailerPatch(RetailerIn):
    """Same shape as RetailerIn, but nothing is required.

    Only the fields actually sent are written, so editing a phone number
    cannot silently reset a credit limit to its default.
    """

    shop_name: str | None = Field(default=None, min_length=2)
    party_type: str | None = None
    price_mode: str | None = None
    state_name: str | None = None
    state_code: str | None = None
    outlet_type: str | None = None
    credit_limit: Decimal | None = None
    credit_days: int | None = None
    is_active: bool | None = None


# --- purchases -------------------------------------------------------------


class PurchaseLineIn(BaseModel):
    product_id: int
    batch_no: str = Field(min_length=1, max_length=40)
    mfg_date: dt.date
    expiry_date: dt.date | None = None
    cases: int = Field(default=0, ge=0)
    loose_pieces: int = Field(default=0, ge=0)
    rate_per_piece: Decimal | None = None


class PurchaseIn(BaseModel):
    supplier_name: str
    company_invoice_no: str
    company_invoice_date: dt.date
    received_on: dt.date
    note: str | None = None
    lines: list[PurchaseLineIn] = Field(min_length=1)


class PurchaseLineOut(ApiModel):
    product_id: int
    product_name: str
    sku_code: str
    batch_no: str
    mfg_date: dt.date
    expiry_date: dt.date
    cases: int
    loose_pieces: int
    qty_pieces: int
    rate_per_piece: Decimal
    taxable: Decimal
    tax_amount: Decimal
    line_total: Decimal

    @field_serializer("rate_per_piece", "taxable", "tax_amount", "line_total")
    def _ser(self, value: Decimal) -> float:
        return money(value)


class PurchaseOut(ApiModel):
    id: int
    grn_no: str
    supplier_name: str
    company_invoice_no: str
    company_invoice_date: dt.date
    received_on: dt.date
    taxable_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    line_count: int = 0
    note: str | None = None
    lines: list[PurchaseLineOut] = []

    @field_serializer("taxable_total", "tax_total", "grand_total")
    def _ser(self, value: Decimal) -> float:
        return money(value)


# --- invoicing -------------------------------------------------------------


class InvoiceLineIn(BaseModel):
    product_id: int
    cases: int = Field(default=0, ge=0)
    loose_pieces: int = Field(default=0, ge=0)
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    # Overrides the product's PTR/PTD for this line only; the trade haggles.
    rate_per_piece: Decimal | None = Field(default=None, gt=0)
    is_free: bool = False


class InvoiceIn(BaseModel):
    retailer_id: int
    invoice_date: dt.date | None = None
    note: str | None = None
    lines: list[InvoiceLineIn] = Field(min_length=1)
    # Overrides the party's usual quoting convention for this bill only.
    price_mode: str | None = None
    # How the goods leave. Null is a solo bill the buyer collects himself;
    # an id puts the bill on that van run.
    delivery_id: int | None = None


class InvoiceLineOut(ApiModel):
    id: int
    product_id: int
    sku_code: str
    product_name: str
    hsn: str
    cases: int
    loose_pieces: int
    qty_pieces: int
    rate_per_piece: Decimal
    quoted_rate_per_piece: Decimal | None = None
    gross: Decimal
    discount: Decimal
    taxable: Decimal
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    line_total: Decimal
    is_free: bool
    batches: list[dict] = []

    @field_serializer(
        "rate_per_piece", "quoted_rate_per_piece", "gross", "discount",
        "taxable", "gst_rate", "cgst", "sgst", "igst", "line_total",
    )
    def _ser(self, value: Decimal) -> float:
        return money(value)


class InvoiceOut(ApiModel):
    id: int
    invoice_no: str
    invoice_date: dt.date
    due_date: dt.date
    retailer_id: int
    retailer_name: str
    retailer_gstin: str | None = None
    route_name: str | None = None
    place_of_supply: str
    is_interstate: bool
    price_mode: str = "exclusive"
    party_type: str = "retailer"
    taxable_total: Decimal
    discount_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    round_off: Decimal
    grand_total: Decimal
    amount_paid: Decimal = Decimal("0")
    credited: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    status: str
    note: str | None = None
    delivery_id: int | None = None
    delivery_no: str | None = None
    lines: list[InvoiceLineOut] = []
    hsn_summary: list[dict] = []
    amount_in_words: str | None = None

    @field_serializer(
        "taxable_total", "discount_total", "cgst_total", "sgst_total",
        "igst_total", "round_off", "grand_total", "amount_paid", "credited",
        "balance",
    )
    def _ser(self, value: Decimal) -> float:
        return money(value)


class InvoicePreviewIn(BaseModel):
    retailer_id: int
    invoice_date: dt.date | None = None
    price_mode: str | None = None
    lines: list[InvoiceLineIn] = Field(min_length=1)


# --- payments --------------------------------------------------------------


class AllocationIn(BaseModel):
    invoice_id: int
    amount: Decimal = Field(gt=0)


class PaymentIn(BaseModel):
    retailer_id: int
    payment_date: dt.date | None = None
    mode: str = "cash"
    amount: Decimal = Field(gt=0)
    reference: str | None = None
    note: str | None = None
    # Left empty, the payment is applied to the oldest open invoices first.
    allocations: list[AllocationIn] = []


class PaymentOut(ApiModel):
    id: int
    receipt_no: str
    retailer_id: int
    retailer_name: str
    payment_date: dt.date
    mode: str
    amount: Decimal
    reference: str | None = None
    note: str | None = None
    allocations: list[dict] = []

    @field_serializer("amount")
    def _ser(self, value: Decimal) -> float:
        return money(value)


class OpenInvoiceOut(ApiModel):
    id: int
    invoice_no: str
    invoice_date: dt.date
    due_date: dt.date
    grand_total: Decimal
    amount_paid: Decimal
    credited: Decimal = Decimal("0")
    balance: Decimal
    days_overdue: int

    @field_serializer("grand_total", "amount_paid", "credited", "balance")
    def _ser(self, value: Decimal) -> float:
        return money(value)


# --- orders, load sheets and returns ---------------------------------------


class OrderLineIn(BaseModel):
    product_id: int
    cases: int = Field(default=0, ge=0)
    loose_pieces: int = Field(default=0, ge=0)
    is_free: bool = False


class OrderIn(BaseModel):
    retailer_id: int
    order_date: dt.date | None = None
    requested_for: dt.date | None = None
    note: str | None = None
    lines: list[OrderLineIn] = Field(min_length=1)


class CreditNoteLineIn(BaseModel):
    invoice_line_id: int
    cases: int = Field(default=0, ge=0)
    loose_pieces: int = Field(default=0, ge=0)


class CreditNoteIn(BaseModel):
    invoice_id: int
    reason: str
    note_date: dt.date | None = None
    note: str | None = None
    lines: list[CreditNoteLineIn] = Field(min_length=1)


# --- van runs (bills the owner is delivering) ------------------------------


class DeliveryIn(BaseModel):
    """Start a run. It begins empty; bills are attached to it afterwards."""

    delivery_date: dt.date | None = None
    note: str | None = None


class DeliveryEdit(BaseModel):
    """Change the note. Never the bills -- those have their own endpoints,
    because attaching a bill is a different decision."""

    note: str | None = None


class DeliveryStatusIn(BaseModel):
    status: str
