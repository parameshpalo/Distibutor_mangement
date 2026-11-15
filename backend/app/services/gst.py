"""GST computation.

Rates are resolved against the document date from the dated `gst_rates`
table, never read off the product, so reprinting an old invoice reproduces
the rate that applied when it was raised.

For an intrastate supply CGST and SGST are each computed at half the slab
rate, which is how the law expresses it and avoids a stray paise from
halving a rounded total. For interstate supply the whole slab is IGST.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import GstRate
from ..money import ZERO, q2

RUPEE = Decimal("1")


def rate_for_hsn(db: Session, hsn: str, on_date: dt.date) -> Decimal:
    """The slab percentage in force for this HSN on this date."""
    stmt = (
        select(GstRate)
        .where(
            GstRate.hsn == hsn,
            GstRate.effective_from <= on_date,
            or_(GstRate.effective_to.is_(None), GstRate.effective_to >= on_date),
        )
        .order_by(GstRate.effective_from.desc())
        .limit(1)
    )
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise ValueError(
            f"No GST rate configured for HSN {hsn} on {on_date:%d-%b-%Y}. "
            "Add it under GST rates before billing this product."
        )
    return Decimal(str(row.rate))


@dataclass
class ComputedLine:
    """One tax-computed invoice line, all values already quantized."""

    qty_pieces: int
    rate_per_piece: Decimal
    gross: Decimal
    discount: Decimal
    taxable: Decimal
    gst_rate: Decimal
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    igst: Decimal = ZERO
    line_total: Decimal = ZERO
    # Set only on a bill quoted inclusive of GST: the all-in rate the buyer
    # agreed to, kept so the bill can be reprinted showing what was said.
    quoted_rate: Decimal | None = None

    @property
    def tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst


def compute_line(
    *,
    qty_pieces: int,
    rate_per_piece: Decimal,
    gst_rate: Decimal,
    discount: Decimal = ZERO,
    is_interstate: bool = False,
    is_free: bool = False,
    price_inclusive: bool = False,
) -> ComputedLine:
    """Tax one line.

    A free-goods line carries quantity but no value, which is how scheme
    giveaways are shown on a tax invoice.

    With `price_inclusive` the rate already contains the tax, which is how
    an unregistered shop usually buys: one all-in figure per case. The tax
    is backed out of it rather than added on top, so the buyer pays what
    was agreed. Nothing else changes — the supply is taxed at the same
    slab, the taxable value and tax are recorded separately, and it reaches
    GSTR-1 exactly as any other sale does. This is a quoting convention,
    not a way to leave a sale out of the books.
    """
    rate_per_piece = Decimal(str(rate_per_piece))
    gst_rate = Decimal(str(gst_rate))
    discount = q2(discount)

    if is_free:
        discount = ZERO

    if price_inclusive and not is_free:
        return _inclusive_line(
            qty_pieces=qty_pieces,
            quoted_rate=rate_per_piece,
            gst_rate=gst_rate,
            discount=discount,
            is_interstate=is_interstate,
        )

    gross = ZERO if is_free else q2(rate_per_piece * qty_pieces)
    if discount > gross:
        raise ValueError("Line discount cannot exceed the line value.")
    taxable = q2(gross - discount)

    line = ComputedLine(
        qty_pieces=qty_pieces,
        rate_per_piece=rate_per_piece,
        gross=gross,
        discount=discount,
        taxable=taxable,
        gst_rate=gst_rate,
        quoted_rate=rate_per_piece if price_inclusive else None,
    )

    if is_interstate:
        line.igst = q2(taxable * gst_rate / 100)
    else:
        half = gst_rate / 2
        line.cgst = q2(taxable * half / 100)
        line.sgst = line.cgst

    line.line_total = q2(taxable + line.tax)
    return line


def _inclusive_line(
    *,
    qty_pieces: int,
    quoted_rate: Decimal,
    gst_rate: Decimal,
    discount: Decimal,
    is_interstate: bool,
) -> ComputedLine:
    """Back the tax out of an all-in rate.

    The tax is rounded first and the taxable value is the balancing figure,
    not the other way round. Rounding the taxable value first and then the
    tax can leave the line a paise away from the figure the buyer agreed —
    and the whole point of an inclusive quote is that it lands exactly on
    it. CGST and SGST are each rounded from the same half-rate so they stay
    equal, as the law requires.
    """
    incl_gross = q2(quoted_rate * qty_pieces)
    if discount > incl_gross:
        raise ValueError("Line discount cannot exceed the line value.")
    incl_net = q2(incl_gross - discount)

    cgst = sgst = igst = ZERO
    if is_interstate:
        igst = q2(incl_net * gst_rate / (100 + gst_rate))
    else:
        cgst = q2(incl_net * (gst_rate / 2) / (100 + gst_rate))
        sgst = cgst
    taxable = q2(incl_net - cgst - sgst - igst)

    # Restate the discount net of tax so that gross - discount == taxable,
    # which is what the e-invoice schema and the HSN summary assume.
    discount_ex = q2(discount * 100 / (100 + gst_rate))
    gross = q2(taxable + discount_ex)

    line = ComputedLine(
        qty_pieces=qty_pieces,
        rate_per_piece=(gross / qty_pieces) if qty_pieces else ZERO,
        gross=gross,
        discount=discount_ex,
        taxable=taxable,
        gst_rate=gst_rate,
        quoted_rate=quoted_rate,
    )
    line.cgst, line.sgst, line.igst = cgst, sgst, igst
    line.line_total = q2(taxable + line.tax)
    return line


@dataclass
class InvoiceTotals:
    taxable_total: Decimal = ZERO
    discount_total: Decimal = ZERO
    cgst_total: Decimal = ZERO
    sgst_total: Decimal = ZERO
    igst_total: Decimal = ZERO
    tax_total: Decimal = ZERO
    subtotal: Decimal = ZERO
    round_off: Decimal = ZERO
    grand_total: Decimal = ZERO
    hsn_summary: list[dict] = field(default_factory=list)


def compute_totals(
    lines: list[ComputedLine], hsn_of_line: list[str] | None = None
) -> InvoiceTotals:
    """Sum lines and round the payable figure to the nearest rupee."""
    totals = InvoiceTotals()
    for line in lines:
        totals.taxable_total += line.taxable
        totals.discount_total += line.discount
        totals.cgst_total += line.cgst
        totals.sgst_total += line.sgst
        totals.igst_total += line.igst

    totals.tax_total = totals.cgst_total + totals.sgst_total + totals.igst_total
    totals.subtotal = q2(totals.taxable_total + totals.tax_total)
    rounded = totals.subtotal.quantize(RUPEE)
    totals.round_off = q2(rounded - totals.subtotal)
    totals.grand_total = q2(rounded)

    if hsn_of_line:
        buckets: dict[tuple[str, Decimal], dict] = {}
        for hsn, line in zip(hsn_of_line, lines, strict=True):
            key = (hsn, line.gst_rate)
            bucket = buckets.setdefault(
                key,
                {
                    "hsn": hsn,
                    "gst_rate": line.gst_rate,
                    "qty_pieces": 0,
                    "taxable": ZERO,
                    "cgst": ZERO,
                    "sgst": ZERO,
                    "igst": ZERO,
                },
            )
            bucket["qty_pieces"] += line.qty_pieces
            bucket["taxable"] += line.taxable
            bucket["cgst"] += line.cgst
            bucket["sgst"] += line.sgst
            bucket["igst"] += line.igst
        totals.hsn_summary = sorted(buckets.values(), key=lambda b: b["hsn"])

    return totals


_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_TENS = (
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
    "Eighty", "Ninety",
)


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def amount_in_words(amount: Decimal) -> str:
    """Render rupees in the Indian lakh/crore system, as invoices require."""
    amount = q2(amount)
    negative = amount < 0
    amount = abs(amount)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    if rupees == 0:
        parts = ["Zero"]
    else:
        parts = []
        crore, rest = divmod(rupees, 10_000_000)
        lakh, rest = divmod(rest, 100_000)
        thousand, rest = divmod(rest, 1_000)
        hundred, below = divmod(rest, 100)
        if crore:
            parts.append(f"{_two_digits(crore)} Crore")
        if lakh:
            parts.append(f"{_two_digits(lakh)} Lakh")
        if thousand:
            parts.append(f"{_two_digits(thousand)} Thousand")
        if hundred:
            parts.append(f"{_ONES[hundred]} Hundred")
        if below:
            parts.append(_two_digits(below))

    words = " ".join(parts)
    text = f"Rupees {words}"
    if paise:
        text += f" and {_two_digits(paise)} Paise"
    text += " Only"
    return ("Minus " + text) if negative else text
