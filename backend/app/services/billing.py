"""Raising a tax invoice.

The whole sequence — price lookup, GST at the dated slab, FEFO batch
allocation, stock postings and numbering — lives here so the HTTP layer and
any future importer or bulk upload follow exactly the same path.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CompanyProfile,
    Delivery,
    Invoice,
    InvoiceLine,
    InvoiceLineBatch,
    Product,
    Retailer,
)
from ..money import ZERO, q2
from . import numbering, stock
from .gst import amount_in_words, compute_line, compute_totals, rate_for_hsn


class BillingError(ValueError):
    """A problem the biller can act on, safe to show at the till."""


# There is deliberately no CreditLimitExceeded any more.
#
# The credit limit used to refuse the bill outright. In a distribution
# business the bill is written at the shop counter with the goods already off
# the van, and a refusal at that moment helps nobody: the owner knows which of
# his shops he will carry and which he will not, and the app does not. So the
# limit is now reported as a warning on the billing screen and on the Money
# page -- before the bill, where it can still change the decision -- and the
# bill itself always goes through.
#
# A happy side effect: `create_invoice` no longer has to price the bill twice,
# which was the only reason `price_invoice` had to stay read-only.


def company(db: Session) -> CompanyProfile:
    profile = db.execute(select(CompanyProfile).limit(1)).scalar_one_or_none()
    if profile is None:
        raise BillingError(
            "No company profile has been set up yet. Complete setup before billing."
        )
    return profile


def _resolve_quantities(product: Product, cases: int, loose_pieces: int) -> int:
    qty = cases * product.pieces_per_case + loose_pieces
    if qty <= 0:
        raise BillingError(
            f"{product.display_name}: enter at least one case or a loose quantity."
        )
    return qty


def price_invoice(
    db: Session,
    *,
    retailer: Retailer,
    line_inputs: list[dict],
    invoice_date: dt.date,
    profile: CompanyProfile | None = None,
    allocate: bool = True,
    price_mode: str | None = None,
) -> dict:
    """Cost an invoice without saving it.

    Used both by the live preview on the billing screen and by the real
    create path, so what the biller sees is what gets written.

    With `allocate` false the lines are priced but no batches are chosen,
    which is what the preview wants when a line is already known to be short:
    the value can still be shown even though the allocation would fail.

    **This function must stay read-only.** The billing screen calls it on
    every keystroke for the live preview, and a bill going out on a van is priced here
    before it is billed. `allocate_fefo` reserves nothing, which is the only
    reason that is safe: anything added here that consumed stock would empty
    the van while the biller was still typing.
    """
    profile = profile or company(db)
    interstate = retailer.state_code != profile.state_code
    # A sub-distributor buys at PTD and resells onward; a shop buys at PTR.
    is_distributor = retailer.party_type == "distributor"
    # The party's usual quoting convention, overridable per bill.
    inclusive = (
        price_mode
        if price_mode is not None
        else (retailer.price_mode or "exclusive")
    ) == "inclusive"

    prepared = []
    computed = []
    hsns = []

    for raw in line_inputs:
        product = db.get(Product, raw["product_id"])
        if product is None or not product.is_active:
            raise BillingError(f"Product {raw['product_id']} is not available.")

        qty = _resolve_quantities(product, raw.get("cases", 0), raw.get("loose_pieces", 0))
        is_free = bool(raw.get("is_free"))
        gst_rate = rate_for_hsn(db, product.hsn, invoice_date)
        rate = Decimal(str(product.ptd if is_distributor else product.ptr))
        if raw.get("rate_per_piece") is not None:
            rate = Decimal(str(raw["rate_per_piece"]))
        if inclusive:
            # The quoted all-in rate is the list price plus the tax that
            # would have been added to it, so the same product lands on the
            # same money whichever way the party likes to be quoted.
            rate = q2(rate * (100 + gst_rate) / 100)

        discount = ZERO
        pct = raw.get("discount_pct")
        if pct is None:
            pct = product.default_discount_pct
        if pct is not None and not is_free:
            discount = q2(rate * qty * Decimal(str(pct)) / 100)

        calc = compute_line(
            qty_pieces=qty,
            rate_per_piece=rate,
            gst_rate=gst_rate,
            discount=discount,
            is_interstate=interstate,
            is_free=is_free,
            price_inclusive=inclusive,
        )

        # Confirm the stock exists before anything is written. Reads only.
        allocation = (
            stock.allocate_fefo(
                db, product.id, qty, invoice_date
            )
            if allocate
            else []
        )

        prepared.append(
            {
                "product": product,
                "cases": raw.get("cases", 0),
                "loose_pieces": raw.get("loose_pieces", 0),
                "qty_pieces": qty,
                "is_free": is_free,
                "allocation": allocation,
                "calc": calc,
            }
        )
        computed.append(calc)
        hsns.append(product.hsn)

    totals = compute_totals(computed, hsns)
    return {
        "interstate": interstate,
        "price_mode": "inclusive" if inclusive else "exclusive",
        "lines": prepared,
        "totals": totals,
        "amount_in_words": amount_in_words(totals.grand_total),
    }


def create_invoice(
    db: Session,
    *,
    retailer_id: int,
    line_inputs: list[dict],
    invoice_date: dt.date | None = None,
    note: str | None = None,
    price_mode: str | None = None,
    delivery_id: int | None = None,
) -> Invoice:
    """Price the bill, write it and move the stock out of the godown.

    `delivery_id` says how the goods leave. None is a solo bill: the buyer
    takes it away himself. Set means the owner is delivering it, and names
    the van run it travels on. Either way the sale happens here and now --
    the stock leaves, the receivable exists, the invoice is numbered. The
    run is a label on the bill, not a second movement of goods.
    """
    profile = company(db)
    invoice_date = invoice_date or dt.date.today()

    retailer = db.get(Retailer, retailer_id)
    if retailer is None or not retailer.is_active:
        raise BillingError("That retailer is not on the active list.")

    run = None
    if delivery_id is not None:
        run = db.get(Delivery, delivery_id)
        if run is None:
            raise BillingError("That van run does not exist.")
        if run.status == "done":
            raise BillingError(
                f"{run.delivery_no} is finished. Start a new run, or bill this "
                "one as a solo bill the buyer collects."
            )

    priced = price_invoice(
        db,
        retailer=retailer,
        line_inputs=line_inputs,
        invoice_date=invoice_date,
        profile=profile,
        price_mode=price_mode,
    )
    totals = priced["totals"]

    invoice = Invoice(
        invoice_no=numbering.next_invoice_no(db, invoice_date, profile.invoice_prefix),
        invoice_date=invoice_date,
        retailer_id=retailer.id,
        place_of_supply=retailer.state_code,
        is_interstate=priced["interstate"],
        price_mode=priced["price_mode"],
        due_date=invoice_date + dt.timedelta(days=retailer.credit_days),
        taxable_total=totals.taxable_total,
        discount_total=totals.discount_total,
        cgst_total=totals.cgst_total,
        sgst_total=totals.sgst_total,
        igst_total=totals.igst_total,
        round_off=totals.round_off,
        grand_total=totals.grand_total,
        status="issued",
        note=note,
        delivery_id=run.id if run else None,
    )
    db.add(invoice)
    db.flush()

    for prepared in priced["lines"]:
        product = prepared["product"]
        calc = prepared["calc"]
        line = InvoiceLine(
            invoice_id=invoice.id,
            product_id=product.id,
            hsn=product.hsn,
            cases=prepared["cases"],
            loose_pieces=prepared["loose_pieces"],
            qty_pieces=prepared["qty_pieces"],
            rate_per_piece=calc.rate_per_piece,
            quoted_rate_per_piece=calc.quoted_rate,
            gross=calc.gross,
            discount=calc.discount,
            taxable=calc.taxable,
            gst_rate=calc.gst_rate,
            cgst=calc.cgst,
            sgst=calc.sgst,
            igst=calc.igst,
            line_total=calc.line_total,
            is_free=prepared["is_free"],
        )
        db.add(line)
        db.flush()

        for batch_id, taken in prepared["allocation"]:
            db.add(
                InvoiceLineBatch(
                    invoice_line_id=line.id, batch_id=batch_id, qty_pieces=taken
                )
            )
            stock.post_movement(
                db,
                product_id=product.id,
                batch_id=batch_id,
                qty_pieces=-taken,
                reason="sale",
                occurred_on=invoice_date,
                ref_type="invoice",
                ref_id=invoice.id,
            )

    db.commit()
    db.refresh(invoice)
    return invoice
