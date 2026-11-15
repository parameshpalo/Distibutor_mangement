"""Render a GST tax invoice as a PDF.

Carries the particulars a tax invoice must show under Rule 46: both GSTINs,
a unique serial number, HSN codes, taxable value and the tax split by head,
place of supply, the rounded payable amount and that amount in words.

Amounts print as "Rs." rather than the rupee sign, because the built-in
Helvetica encoding has no glyph for it and a missing glyph prints as a box.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..models import CompanyProfile, Invoice
from .gst import amount_in_words

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5b6472")
LINE = colors.HexColor("#c8cdd6")
BAND = colors.HexColor("#eef1f5")

PAISE = Decimal("0.01")

_styles = getSampleStyleSheet()
BASE = ParagraphStyle("base", parent=_styles["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=INK)
SMALL = ParagraphStyle("small", parent=BASE, fontSize=7, leading=8.6, textColor=MUTED)
CELL = ParagraphStyle("cell", parent=BASE, fontSize=7.6, leading=9.2)
CELL_R = ParagraphStyle("cellr", parent=CELL, alignment=TA_RIGHT)
HEAD_CELL = ParagraphStyle("headcell", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
HEAD_CELL_R = ParagraphStyle("headcellr", parent=HEAD_CELL, alignment=TA_RIGHT)
TITLE = ParagraphStyle("title", parent=BASE, fontName="Helvetica-Bold", fontSize=14, leading=16)
DOCTYPE = ParagraphStyle("doctype", parent=BASE, fontName="Helvetica-Bold", fontSize=11, alignment=TA_CENTER, textColor=MUTED)
LABEL = ParagraphStyle("label", parent=BASE, fontName="Helvetica-Bold", fontSize=7.5, textColor=MUTED)


def rupees(value) -> str:
    return f"{Decimal(str(value or 0)):,.2f}"


def _qty_label(cases: int, loose: int, per_case: int) -> str:
    bits = []
    if cases:
        bits.append(f"{cases} cs")
    if loose:
        bits.append(f"{loose} pc")
    return " + ".join(bits) or f"{per_case} pc"


def _pct(value) -> str:
    """A GST rate as people write it: 5, 12, 18.5 — never 5.0000.

    Rates are stored at four decimal places, and Decimal's "g" format
    keeps the trailing zeros, which made the column wrap on the printed
    invoice. `normalize` strips them; the integral case is re-quantized so
    a whole number cannot come back as 1E+2.
    """
    amount = Decimal(str(value)).normalize()
    if amount == amount.to_integral_value():
        amount = amount.quantize(Decimal(1))
    return f"{amount:f}"


def build_invoice_pdf(invoice: Invoice, company: CompanyProfile) -> bytes:
    """Return the invoice as PDF bytes, ready to print or send."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=f"Tax Invoice {invoice.invoice_no}",
        author=company.trade_name,
    )

    retailer = invoice.retailer
    interstate = invoice.is_interstate
    story: list = []

    # --- letterhead --------------------------------------------------------
    seller_lines = [
        f"<b>{company.trade_name}</b>",
        company.address_line1,
        company.address_line2 or "",
        f"{company.city} - {company.pincode}, {company.state_name}",
        f"GSTIN: <b>{company.gstin}</b>",
    ]
    if company.fssai_no:
        seller_lines.append(f"FSSAI: {company.fssai_no}")
    if company.phone:
        seller_lines.append(f"Phone: {company.phone}")

    story.append(
        Table(
            [[
                Paragraph("<br/>".join(x for x in seller_lines if x), BASE),
                Paragraph("TAX INVOICE", DOCTYPE),
            ]],
            colWidths=[112 * mm, 74 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]),
        )
    )
    story.append(Spacer(1, 3 * mm))

    # --- parties and document details -------------------------------------
    buyer_lines = [
        f"<b>{retailer.shop_name}</b>",
        retailer.owner_name or "",
        retailer.address_line or "",
        f"{retailer.city or ''} {retailer.pincode or ''}".strip(),
        f"{retailer.state_name} ({retailer.state_code})",
        f"GSTIN: {retailer.gstin}" if retailer.gstin else "GSTIN: Unregistered",
    ]
    if retailer.phone:
        buyer_lines.append(f"Phone: {retailer.phone}")

    meta = [
        ("Invoice No.", invoice.invoice_no),
        ("Invoice Date", f"{invoice.invoice_date:%d-%b-%Y}"),
        ("Due Date", f"{invoice.due_date:%d-%b-%Y}"),
        ("Place of Supply", f"{retailer.state_name} ({invoice.place_of_supply})"),
        ("Supply Type", "Inter-State" if interstate else "Intra-State"),
        ("Reverse Charge", "No"),
    ]
    if retailer.route:
        meta.append(("Route", retailer.route.name))

    meta_rows = [
        [Paragraph(label, LABEL), Paragraph(str(value), CELL)] for label, value in meta
    ]

    story.append(
        Table(
            [[
                Table(
                    [[Paragraph("BILLED TO", LABEL)],
                     [Paragraph("<br/>".join(x for x in buyer_lines if x), CELL)]],
                    colWidths=[106 * mm],
                    style=TableStyle([
                        ("BACKGROUND", (0, 0), (0, 0), BAND),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ]),
                ),
                Table(
                    meta_rows,
                    colWidths=[26 * mm, 50 * mm],
                    style=TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
                    ]),
                ),
            ]],
            colWidths=[108 * mm, 78 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
        )
    )
    story.append(Spacer(1, 3.5 * mm))

    # --- line items --------------------------------------------------------
    tax_heads = ["IGST"] if interstate else ["CGST", "SGST"]
    inclusive = getattr(invoice, "price_mode", "exclusive") == "inclusive"
    # On an inclusive bill the figure the buyer agreed is the all-in rate,
    # so that is the one printed. The tax is still broken out alongside it,
    # which Rule 46 requires on a tax invoice either way.
    rate_head = "Rate (incl.)" if inclusive else "Rate"
    header = ["#", "Particulars", "HSN", "Qty", rate_head, "Disc.", "Taxable", "GST%"]
    header += tax_heads + ["Amount"]
    right_from = 3  # columns from here on are numeric

    body = [[
        Paragraph(text, HEAD_CELL if index < right_from else HEAD_CELL_R)
        for index, text in enumerate(header)
    ]]

    for index, line in enumerate(invoice.lines, start=1):
        product = line.product
        name = product.display_name
        if line.is_free:
            name += "  <i>(scheme &mdash; free)</i>"
        row = [
            Paragraph(str(index), CELL),
            Paragraph(name, CELL),
            Paragraph(line.hsn, CELL),
            Paragraph(
                _qty_label(line.cases, line.loose_pieces, product.pieces_per_case),
                CELL_R,
            ),
            Paragraph(
                f"{Decimal(str(line.quoted_rate_per_piece or line.rate_per_piece)):,.4f}",
                CELL_R,
            ),
            Paragraph(rupees(line.discount) if line.discount else "-", CELL_R),
            Paragraph(rupees(line.taxable), CELL_R),
            Paragraph(f"{_pct(line.gst_rate)}%", CELL_R),
        ]
        if interstate:
            row.append(Paragraph(rupees(line.igst), CELL_R))
        else:
            row.append(Paragraph(rupees(line.cgst), CELL_R))
            row.append(Paragraph(rupees(line.sgst), CELL_R))
        row.append(Paragraph(rupees(line.line_total), CELL_R))
        body.append(row)

    # Both sets total 186mm, the printable width of A4 at these margins.
    if interstate:
        widths = [7, 48, 13, 16, 16, 13, 19, 11, 19, 24]
    else:
        widths = [7, 45, 12, 15, 15, 13, 19, 10, 15, 15, 20]
    col_widths = [w * mm for w in widths]

    items = Table(body, colWidths=col_widths, repeatRows=1)
    items.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ])
    )
    story.append(items)
    story.append(Spacer(1, 3 * mm))

    # --- HSN summary and totals, side by side -----------------------------
    hsn_buckets: dict[tuple[str, str], dict] = {}
    for line in invoice.lines:
        key = (line.hsn, _pct(line.gst_rate))
        bucket = hsn_buckets.setdefault(
            key,
            {"taxable": Decimal("0"), "cgst": Decimal("0"), "sgst": Decimal("0"), "igst": Decimal("0")},
        )
        bucket["taxable"] += Decimal(str(line.taxable))
        bucket["cgst"] += Decimal(str(line.cgst))
        bucket["sgst"] += Decimal(str(line.sgst))
        bucket["igst"] += Decimal(str(line.igst))

    hsn_header = ["HSN", "GST%", "Taxable"] + tax_heads
    hsn_rows = [[Paragraph(h, HEAD_CELL if i < 1 else HEAD_CELL_R) for i, h in enumerate(hsn_header)]]
    for (hsn, rate), bucket in sorted(hsn_buckets.items()):
        row = [
            Paragraph(hsn, CELL),
            Paragraph(f"{rate}%", CELL_R),
            Paragraph(rupees(bucket["taxable"]), CELL_R),
        ]
        if interstate:
            row.append(Paragraph(rupees(bucket["igst"]), CELL_R))
        else:
            row.append(Paragraph(rupees(bucket["cgst"]), CELL_R))
            row.append(Paragraph(rupees(bucket["sgst"]), CELL_R))
        hsn_rows.append(row)

    hsn_widths = [16, 12, 24, 20, 20] if not interstate else [18, 14, 28, 28]
    hsn_table = Table(hsn_rows, colWidths=[w * mm for w in hsn_widths])
    hsn_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])
    )

    total_rows = [("Taxable Value", invoice.taxable_total)]
    if Decimal(str(invoice.discount_total)) > 0:
        total_rows.insert(0, ("Scheme Discount", invoice.discount_total))
    if interstate:
        total_rows.append(("IGST", invoice.igst_total))
    else:
        total_rows.append(("CGST", invoice.cgst_total))
        total_rows.append(("SGST", invoice.sgst_total))
    if Decimal(str(invoice.round_off)) != 0:
        total_rows.append(("Round Off", invoice.round_off))

    totals_data = [
        [Paragraph(label, CELL), Paragraph(f"Rs. {rupees(value)}", CELL_R)]
        for label, value in total_rows
    ]
    totals_data.append([
        Paragraph("<b>Total Payable</b>", CELL),
        Paragraph(f"<b>Rs. {rupees(invoice.grand_total)}</b>", CELL_R),
    ])
    totals_table = Table(totals_data, colWidths=[40 * mm, 34 * mm])
    totals_table.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("BACKGROUND", (0, -1), (-1, -1), BAND),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ])
    )

    story.append(
        Table(
            [[hsn_table, totals_table]],
            colWidths=[108 * mm, 78 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]),
        )
    )
    story.append(Spacer(1, 2.5 * mm))
    story.append(
        Paragraph(
            f"<b>Amount in words:</b> {amount_in_words(Decimal(str(invoice.grand_total)))}",
            BASE,
        )
    )
    if inclusive:
        story.append(Spacer(1, 1.5 * mm))
        story.append(
            Paragraph(
                "Rates quoted are inclusive of GST. The tax shown above is "
                "contained in them, not added to them.",
                BASE,
            )
        )
    story.append(Spacer(1, 4 * mm))

    # --- bank details, terms, signature -----------------------------------
    bank_bits = []
    if company.bank_name:
        bank_bits.append(f"<b>Bank:</b> {company.bank_name}")
    if company.bank_account:
        bank_bits.append(f"<b>A/c:</b> {company.bank_account}")
    if company.bank_ifsc:
        bank_bits.append(f"<b>IFSC:</b> {company.bank_ifsc}")

    terms = (
        "1. Goods once sold are not returnable except for damage or short "
        "shelf life, against a credit note.<br/>"
        "2. Please check expiry dates and quantity at the time of delivery.<br/>"
        "3. Interest at 18% p.a. applies on bills outstanding beyond the due date.<br/>"
        f"4. Subject to {company.city} jurisdiction."
    )

    signature_cell = Paragraph(
        f"For <b>{company.trade_name}</b><br/><br/><br/><br/>Authorised Signatory",
        CELL_R,
    )

    story.append(
        KeepTogether(
            Table(
                [[
                    Paragraph(
                        ("<br/>".join(bank_bits) + "<br/><br/>" if bank_bits else "")
                        + f"<b>Terms</b><br/>{terms}",
                        SMALL,
                    ),
                    signature_cell,
                ]],
                colWidths=[122 * mm, 64 * mm],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                ]),
            )
        )
    )

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            12 * mm, 8 * mm,
            f"{company.trade_name} - computer-generated tax invoice "
            f"{invoice.invoice_no}",
        )
        canvas.drawRightString(
            A4[0] - 12 * mm, 8 * mm,
            f"Page {canvas.getPageNumber()}   |   generated {dt.date.today():%d-%b-%Y}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# The shop's own slip
# ---------------------------------------------------------------------------
#
# Many kirana shops are unregistered and do not want a tax invoice on the
# counter. The firm still has to raise one, because the sale is the firm's
# outward supply and goes into GSTR-1 either way. So one sale produces two
# pieces of paper: the tax invoice above, which the firm keeps and files, and
# this memo, which the shop gets with the goods.
#
# What is deliberately absent, and why:
#
#   - no GSTIN, on either side, and no "TAX INVOICE" heading. A document
#     carrying the supplier's GSTIN under that heading is a tax invoice, and
#     handing out two of them for one sale is how a duplicate-invoice
#     problem starts.
#   - no HSN code, no taxable value, no CGST/SGST/IGST split, no place of
#     supply, no reverse-charge line. None of it means anything to the shop,
#     and all of it is what makes the page read as a tax document.
#   - no "amount in words". That is a Rule 46 particular, not a courtesy.
#
# What is deliberately present:
#
#   - the FSSAI licence number, which a food business has to show on the bill
#     it gives a buyer, tax document or not.
#   - the invoice number, as "Bill No." It is the firm's reference and the
#     only thing tying this slip to the sale behind it, and it carries no GST
#     meaning on its own.
#   - one rate per line, tax included, because that is the figure the shop
#     agreed to. The amount against the line is the authority: the rate is
#     derived from it, so rate x quantity can land a few paise away.


def build_cash_memo_pdf(invoice: Invoice, company: CompanyProfile) -> bytes:
    """Return the shop's plain memo for this sale as PDF bytes.

    The money is identical to the tax invoice's: same line amounts, same
    round-off, same payable total. Only the tax presentation is gone.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=f"Cash Memo {invoice.invoice_no}",
        author=company.trade_name,
    )

    retailer = invoice.retailer
    story: list = []

    # --- letterhead, without the GSTIN -------------------------------------
    seller_lines = [
        f"<b>{company.trade_name}</b>",
        company.address_line1,
        company.address_line2 or "",
        f"{company.city} - {company.pincode}, {company.state_name}",
    ]
    if company.fssai_no:
        seller_lines.append(f"FSSAI: {company.fssai_no}")
    if company.phone:
        seller_lines.append(f"Phone: {company.phone}")

    story.append(
        Table(
            [[
                Paragraph("<br/>".join(x for x in seller_lines if x), BASE),
                Paragraph("CASH MEMO", DOCTYPE),
            ]],
            colWidths=[112 * mm, 74 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]),
        )
    )
    story.append(Spacer(1, 3 * mm))

    # --- who, and when -----------------------------------------------------
    buyer_lines = [
        f"<b>{retailer.shop_name}</b>",
        retailer.owner_name or "",
        retailer.address_line or "",
        f"{retailer.city or ''} {retailer.pincode or ''}".strip(),
    ]
    if retailer.phone:
        buyer_lines.append(f"Phone: {retailer.phone}")

    meta_rows = [
        [Paragraph(label, LABEL), Paragraph(str(value), CELL)]
        for label, value in (
            ("Bill No.", invoice.invoice_no),
            ("Date", f"{invoice.invoice_date:%d-%b-%Y}"),
            ("Payment Due", f"{invoice.due_date:%d-%b-%Y}"),
        )
    ]

    story.append(
        Table(
            [[
                Table(
                    [[Paragraph("DELIVERED TO", LABEL)],
                     [Paragraph("<br/>".join(x for x in buyer_lines if x), CELL)]],
                    colWidths=[106 * mm],
                    style=TableStyle([
                        ("BACKGROUND", (0, 0), (0, 0), BAND),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ]),
                ),
                Table(
                    meta_rows,
                    colWidths=[26 * mm, 50 * mm],
                    style=TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
                    ]),
                ),
            ]],
            colWidths=[108 * mm, 78 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
        )
    )
    story.append(Spacer(1, 3.5 * mm))

    # --- the goods: five columns, none of them about tax -------------------
    header = ["#", "Particulars", "Qty", "Rate", "Amount"]
    body = [[
        Paragraph(text, HEAD_CELL if index < 2 else HEAD_CELL_R)
        for index, text in enumerate(header)
    ]]

    for index, line in enumerate(invoice.lines, start=1):
        product = line.product
        pieces = line.cases * product.pieces_per_case + line.loose_pieces
        amount = Decimal(str(line.line_total))
        if line.is_free:
            name = product.display_name + "  <i>(free)</i>"
            rate_text = "-"
        else:
            name = product.display_name
            # Derived from the amount, not taken from the quoted rate: on an
            # exclusive-priced bill the quoted rate is before tax, and
            # printing it on a slip that shows no tax would understate the
            # line by the whole of the GST.
            rate_text = (
                f"{(amount / pieces).quantize(PAISE):,.2f}" if pieces else "-"
            )
        body.append([
            Paragraph(str(index), CELL),
            Paragraph(name, CELL),
            Paragraph(
                _qty_label(line.cases, line.loose_pieces, product.pieces_per_case),
                CELL_R,
            ),
            Paragraph(rate_text, CELL_R),
            Paragraph(rupees(amount), CELL_R),
        ])

    # 186mm, the printable width of A4 at these margins.
    items = Table(body, colWidths=[w * mm for w in (9, 109, 22, 22, 24)], repeatRows=1)
    items.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ])
    )
    story.append(items)
    story.append(Spacer(1, 3 * mm))

    # --- what is owed ------------------------------------------------------
    # The line amounts already carry the tax, so the only thing between their
    # sum and the payable figure is the round-off the invoice applied. It is
    # shown when there is one, so the arithmetic on the slip closes.
    total_rows = []
    if Decimal(str(invoice.round_off)) != 0:
        total_rows.append((
            "Goods",
            sum((Decimal(str(x.line_total)) for x in invoice.lines), Decimal("0")),
        ))
        total_rows.append(("Round Off", invoice.round_off))

    totals_data = [
        [Paragraph(label, CELL), Paragraph("Rs. " + rupees(value), CELL_R)]
        for label, value in total_rows
    ]
    totals_data.append([
        Paragraph("<b>Total</b>", CELL),
        Paragraph("<b>Rs. " + rupees(invoice.grand_total) + "</b>", CELL_R),
    ])
    totals_table = Table(totals_data, colWidths=[40 * mm, 34 * mm])
    totals_table.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("BACKGROUND", (0, -1), (-1, -1), BAND),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ])
    )
    story.append(
        Table(
            [["", totals_table]],
            colWidths=[108 * mm, 78 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]),
        )
    )
    story.append(Spacer(1, 4 * mm))

    story.append(
        KeepTogether(
            Table(
                [[
                    Paragraph(
                        "Rates shown include tax. Please check quantity and "
                        "expiry dates before accepting delivery.<br/>"
                        "Goods are returnable only for damage or short shelf "
                        "life.",
                        SMALL,
                    ),
                    Paragraph(
                        "For <b>" + company.trade_name + "</b><br/><br/><br/>"
                        "<br/>Received the goods above",
                        CELL_R,
                    ),
                ]],
                colWidths=[122 * mm, 64 * mm],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                ]),
            )
        )
    )

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(MUTED)
        # Says plainly what the page is not, so nobody files it as one.
        canvas.drawString(
            12 * mm, 8 * mm,
            company.trade_name + " - cash memo " + invoice.invoice_no
            + ". This is not a tax invoice.",
        )
        canvas.drawRightString(
            A4[0] - 12 * mm, 8 * mm,
            f"Page {canvas.getPageNumber()}   |   generated {dt.date.today():%d-%b-%Y}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
