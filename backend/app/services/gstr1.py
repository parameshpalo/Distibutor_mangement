"""GSTR-1: the monthly return of outward supplies.

Built straight from the invoices and credit notes rather than from a
running tally, so the return always agrees with the books. The sections a
distributor of this size actually files:

    B2B    invoice-wise supplies to registered buyers (Table 4A)
    B2CL   interstate supplies to unregistered buyers above the threshold
    B2CS   everything else B2C, summarised by place of supply and rate
    CDNR   credit and debit notes issued to registered buyers (Table 9B)
    HSN    HSN-wise summary of outward supplies (Table 12)
    DOCS   document series issued, with any gaps (Table 13)

One subtlety worth stating, because getting it wrong is common: a credit
note to an *unregistered* buyer is not reported in CDNUR unless the
original supply was B2CL. For ordinary B2C it is netted off inside the
B2CS figures instead, which is what this module does.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import CompanyProfile, CreditNote, Invoice
from ..money import ZERO, q2

#: The portal wants dates as dd-mm-yyyy and the period as MMYYYY.
GST_DATE = "%d-%m-%Y"


def period_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    end = dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    return start, end


def filing_period(year: int, month: int) -> str:
    return f"{month:02d}{year}"


def _f(value) -> float:
    """Money as the portal wants it: a number at two decimals."""
    return float(q2(value or 0))


def _rate_key(value) -> float:
    rate = float(value or 0)
    return int(rate) if rate == int(rate) else rate


class Gstr1Builder:
    """Assembles one month's return."""

    def __init__(self, db: Session, year: int, month: int):
        self.db = db
        self.year = year
        self.month = month
        self.start, self.end = period_bounds(year, month)
        self.settings = get_settings()
        self.company = db.execute(select(CompanyProfile).limit(1)).scalar_one()

    # --- source data ---------------------------------------------------

    def invoices(self) -> list[Invoice]:
        return list(
            self.db.execute(
                select(Invoice)
                .where(
                    Invoice.invoice_date >= self.start,
                    Invoice.invoice_date <= self.end,
                    Invoice.status == "issued",
                )
                .order_by(Invoice.invoice_no)
            ).scalars()
        )

    def credit_notes(self) -> list[CreditNote]:
        return list(
            self.db.execute(
                select(CreditNote)
                .where(
                    CreditNote.note_date >= self.start,
                    CreditNote.note_date <= self.end,
                )
                .order_by(CreditNote.note_no)
            ).scalars()
        )

    # --- sections ------------------------------------------------------

    def _items(self, lines) -> list[dict]:
        """Rate-wise item blocks, which is how the portal wants a document."""
        buckets: dict[float, dict] = {}
        for line in lines:
            rate = _rate_key(line.gst_rate)
            bucket = buckets.setdefault(
                rate,
                {"rt": rate, "txval": ZERO, "camt": ZERO, "samt": ZERO,
                 "iamt": ZERO, "csamt": ZERO},
            )
            bucket["txval"] += Decimal(str(line.taxable))
            bucket["camt"] += Decimal(str(line.cgst))
            bucket["samt"] += Decimal(str(line.sgst))
            bucket["iamt"] += Decimal(str(line.igst))

        items = []
        for number, rate in enumerate(sorted(buckets), start=1):
            bucket = buckets[rate]
            detail = {
                "rt": rate,
                "txval": _f(bucket["txval"]),
                "csamt": 0,
            }
            if bucket["iamt"] > 0:
                detail["iamt"] = _f(bucket["iamt"])
            else:
                detail["camt"] = _f(bucket["camt"])
                detail["samt"] = _f(bucket["samt"])
            items.append({"num": number, "itm_det": detail})
        return items

    def b2b(self, invoices: list[Invoice]) -> list[dict]:
        """Invoice-wise supplies to registered buyers, grouped by their GSTIN."""
        by_gstin: dict[str, list[Invoice]] = defaultdict(list)
        for invoice in invoices:
            if invoice.retailer.gstin:
                by_gstin[invoice.retailer.gstin].append(invoice)

        out = []
        for gstin in sorted(by_gstin):
            out.append({
                "ctin": gstin,
                "inv": [
                    {
                        "inum": invoice.invoice_no,
                        "idt": invoice.invoice_date.strftime(GST_DATE),
                        "val": _f(invoice.grand_total),
                        "pos": invoice.place_of_supply,
                        "rchrg": "N",
                        "inv_typ": "R",
                        "itms": self._items(invoice.lines),
                    }
                    for invoice in sorted(by_gstin[gstin], key=lambda i: i.invoice_no)
                ],
            })
        return out

    def b2cl(self, invoices: list[Invoice]) -> list[dict]:
        """Interstate B2C invoices above the threshold, reported invoice-wise."""
        threshold = self.settings.b2cl_threshold
        by_pos: dict[str, list[Invoice]] = defaultdict(list)
        for invoice in invoices:
            if (
                not invoice.retailer.gstin
                and invoice.is_interstate
                and Decimal(str(invoice.grand_total)) > threshold
            ):
                by_pos[invoice.place_of_supply].append(invoice)

        return [
            {
                "pos": pos,
                "inv": [
                    {
                        "inum": invoice.invoice_no,
                        "idt": invoice.invoice_date.strftime(GST_DATE),
                        "val": _f(invoice.grand_total),
                        "itms": self._items(invoice.lines),
                    }
                    for invoice in sorted(by_pos[pos], key=lambda i: i.invoice_no)
                ],
            }
            for pos in sorted(by_pos)
        ]

    def b2cs(self, invoices: list[Invoice], notes: list[CreditNote]) -> list[dict]:
        """Everything else B2C, summarised by supply type, place and rate.

        Credit notes to unregistered buyers are netted off here rather than
        reported separately, so this can legitimately go negative for a
        place-and-rate combination in a month of heavy returns.
        """
        threshold = self.settings.b2cl_threshold
        buckets: dict[tuple[str, str, float], dict] = {}

        def bucket_for(supply_type: str, pos: str, rate: float) -> dict:
            return buckets.setdefault(
                (supply_type, pos, rate),
                {
                    "sply_ty": supply_type,
                    "pos": pos,
                    "typ": "OE",
                    "rt": rate,
                    "txval": ZERO,
                    "camt": ZERO,
                    "samt": ZERO,
                    "iamt": ZERO,
                    "csamt": 0,
                },
            )

        for invoice in invoices:
            if invoice.retailer.gstin:
                continue
            if (
                invoice.is_interstate
                and Decimal(str(invoice.grand_total)) > threshold
            ):
                continue  # reported in B2CL instead
            supply_type = "INTER" if invoice.is_interstate else "INTRA"
            for line in invoice.lines:
                bucket = bucket_for(
                    supply_type, invoice.place_of_supply, _rate_key(line.gst_rate)
                )
                bucket["txval"] += Decimal(str(line.taxable))
                bucket["camt"] += Decimal(str(line.cgst))
                bucket["samt"] += Decimal(str(line.sgst))
                bucket["iamt"] += Decimal(str(line.igst))

        for note in notes:
            if note.retailer.gstin:
                continue  # goes to CDNR
            original = note.invoice
            if (
                note.is_interstate
                and Decimal(str(original.grand_total)) > threshold
            ):
                continue  # belongs with the B2CL supply, via CDNUR
            supply_type = "INTER" if note.is_interstate else "INTRA"
            for line in note.lines:
                bucket = bucket_for(
                    supply_type, note.place_of_supply, _rate_key(line.gst_rate)
                )
                bucket["txval"] -= Decimal(str(line.taxable))
                bucket["camt"] -= Decimal(str(line.cgst))
                bucket["samt"] -= Decimal(str(line.sgst))
                bucket["iamt"] -= Decimal(str(line.igst))

        rows = []
        for key in sorted(buckets):
            bucket = buckets[key]
            row = {
                "sply_ty": bucket["sply_ty"],
                "pos": bucket["pos"],
                "typ": "OE",
                "rt": bucket["rt"],
                "txval": _f(bucket["txval"]),
                "csamt": 0,
            }
            if bucket["sply_ty"] == "INTER":
                row["iamt"] = _f(bucket["iamt"])
            else:
                row["camt"] = _f(bucket["camt"])
                row["samt"] = _f(bucket["samt"])
            rows.append(row)
        return rows

    def cdnr(self, notes: list[CreditNote]) -> list[dict]:
        """Credit notes issued to registered buyers, note-wise."""
        by_gstin: dict[str, list[CreditNote]] = defaultdict(list)
        for note in notes:
            if note.retailer.gstin:
                by_gstin[note.retailer.gstin].append(note)

        return [
            {
                "ctin": gstin,
                "nt": [
                    {
                        "ntty": "C",
                        "nt_num": note.note_no,
                        "nt_dt": note.note_date.strftime(GST_DATE),
                        "p_gst": "N",
                        "inum": note.invoice.invoice_no,
                        "idt": note.invoice.invoice_date.strftime(GST_DATE),
                        "val": _f(note.grand_total),
                        "pos": note.place_of_supply,
                        "rchrg": "N",
                        "inv_typ": "R",
                        "itms": self._items(note.lines),
                    }
                    for note in sorted(by_gstin[gstin], key=lambda n: n.note_no)
                ],
            }
            for gstin in sorted(by_gstin)
        ]

    def hsn(self, invoices: list[Invoice], notes: list[CreditNote]) -> dict:
        """Table 12, net of credit notes, with quantity in the product's unit."""
        digits = self.settings.hsn_digits
        buckets: dict[tuple[str, float], dict] = {}

        def bucket_for(hsn: str, rate: float) -> dict:
            code = (hsn or "")[:digits]
            return buckets.setdefault(
                (code, rate),
                {
                    "hsn_sc": code,
                    "desc": "Biscuits and sweet biscuits",
                    "uqc": "PCS",
                    "rt": rate,
                    "qty": 0,
                    "txval": ZERO,
                    "camt": ZERO,
                    "samt": ZERO,
                    "iamt": ZERO,
                    "csamt": 0,
                },
            )

        for invoice in invoices:
            for line in invoice.lines:
                bucket = bucket_for(line.hsn, _rate_key(line.gst_rate))
                bucket["qty"] += line.qty_pieces
                bucket["txval"] += Decimal(str(line.taxable))
                bucket["camt"] += Decimal(str(line.cgst))
                bucket["samt"] += Decimal(str(line.sgst))
                bucket["iamt"] += Decimal(str(line.igst))

        for note in notes:
            for line in note.lines:
                bucket = bucket_for(line.hsn, _rate_key(line.gst_rate))
                bucket["qty"] -= line.qty_pieces
                bucket["txval"] -= Decimal(str(line.taxable))
                bucket["camt"] -= Decimal(str(line.cgst))
                bucket["samt"] -= Decimal(str(line.sgst))
                bucket["iamt"] -= Decimal(str(line.igst))

        data = []
        for number, key in enumerate(sorted(buckets), start=1):
            bucket = buckets[key]
            data.append({
                "num": number,
                "hsn_sc": bucket["hsn_sc"],
                "desc": bucket["desc"],
                "uqc": bucket["uqc"],
                "qty": bucket["qty"],
                "rt": bucket["rt"],
                "txval": _f(bucket["txval"]),
                "iamt": _f(bucket["iamt"]),
                "camt": _f(bucket["camt"]),
                "samt": _f(bucket["samt"]),
                "csamt": 0,
            })
        return {"data": data}

    def doc_issue(self) -> dict:
        """Table 13: the document series issued, and any gap in them.

        A gap is worth surfacing even though the portal only wants counts,
        because a missing invoice number is the kind of thing that turns
        into a notice.
        """
        series = [
            ("Invoices for outward supply", self._series(Invoice, "invoice_no",
                                                         "invoice_date")),
            ("Credit notes", self._series(CreditNote, "note_no", "note_date")),
        ]
        doc_det = []
        for number, (label, rows) in enumerate(series, start=1):
            if not rows["docs"]:
                continue
            doc_det.append({
                "doc_num": number,
                "doc_typ": label,
                "docs": rows["docs"],
            })
        return {"doc_det": doc_det, "gaps": [g for _, r in series for g in r["gaps"]]}

    def _series(self, model, number_field: str, date_field: str) -> dict:
        rows = list(
            self.db.execute(
                select(model)
                .where(
                    getattr(model, date_field) >= self.start,
                    getattr(model, date_field) <= self.end,
                )
                .order_by(getattr(model, number_field))
            ).scalars()
        )
        if not rows:
            return {"docs": [], "gaps": []}

        numbers = [getattr(row, number_field) for row in rows]
        cancelled = sum(1 for row in rows if getattr(row, "status", "") == "cancelled")

        # The numeric tail is the running counter; a break in it is a gap.
        def tail(value: str) -> int | None:
            last = value.rsplit("/", 1)[-1]
            return int(last) if last.isdigit() else None

        # Numbering runs across the whole financial year, not per month, so a
        # number absent from this period is only a gap if it was never issued
        # at all. Checking against the period alone would flag every document
        # that happened to fall in an adjacent month.
        all_numbers = list(
            self.db.execute(select(getattr(model, number_field))).scalars()
        )
        issued = {t for t in (tail(n) for n in all_numbers) if t is not None}

        tails = sorted(t for t in (tail(n) for n in numbers) if t is not None)
        gaps = []
        if tails:
            missing = set(range(tails[0], tails[-1] + 1)) - issued
            if missing:
                prefix = numbers[0].rsplit("/", 1)[0]
                width = len(numbers[0].rsplit("/", 1)[-1])
                gaps = [f"{prefix}/{m:0{width}d}" for m in sorted(missing)]

        return {
            "docs": [{
                "num": 1,
                "from": numbers[0],
                "to": numbers[-1],
                "totnum": len(numbers),
                "cancel": cancelled,
                "net_issue": len(numbers) - cancelled,
            }],
            "gaps": gaps,
        }

    # --- assembly ------------------------------------------------------

    def build(self) -> dict:
        invoices = self.invoices()
        notes = self.credit_notes()

        b2b = self.b2b(invoices)
        b2cl = self.b2cl(invoices)
        b2cs = self.b2cs(invoices, notes)
        cdnr = self.cdnr(notes)
        hsn = self.hsn(invoices, notes)
        docs = self.doc_issue()

        return {
            "gstin": self.company.gstin,
            "fp": filing_period(self.year, self.month),
            "version": "GST3.2",
            "hash": "hash",
            "b2b": b2b,
            "b2cl": b2cl,
            "b2cs": b2cs,
            "cdnr": cdnr,
            "hsn": hsn,
            "doc_issue": {"doc_det": docs["doc_det"]},
        }

    def summary(self) -> dict:
        """What the owner needs to see before filing, with the checks."""
        invoices = self.invoices()
        notes = self.credit_notes()
        payload = self.build()

        def section_total(rows, key="txval") -> Decimal:
            total = ZERO
            for row in rows:
                for invoice in row.get("inv", row.get("nt", [])) or []:
                    for item in invoice["itms"]:
                        total += Decimal(str(item["itm_det"][key]))
            return q2(total)

        b2b_taxable = section_total(payload["b2b"])
        b2cl_taxable = section_total(payload["b2cl"])
        b2cs_taxable = q2(sum((Decimal(str(r["txval"])) for r in payload["b2cs"]), ZERO))
        cdnr_taxable = section_total(payload["cdnr"])

        books_invoices = q2(
            sum((Decimal(str(i.taxable_total)) for i in invoices), ZERO)
        )
        books_notes = q2(sum((Decimal(str(n.taxable_total)) for n in notes), ZERO))
        books_net = q2(books_invoices - books_notes)
        return_net = q2(b2b_taxable + b2cl_taxable + b2cs_taxable - cdnr_taxable)

        hsn_taxable = q2(
            sum((Decimal(str(r["txval"])) for r in payload["hsn"]["data"]), ZERO)
        )

        docs = self.doc_issue()

        checks = [
            {
                "label": "Sections reconcile to the books",
                "ok": abs(return_net - books_net) < Decimal("1.00"),
                "detail": f"return {float(return_net):,.2f} vs books "
                f"{float(books_net):,.2f}",
            },
            {
                "label": "HSN summary matches the sections",
                "ok": abs(hsn_taxable - books_net) < Decimal("1.00"),
                "detail": f"HSN {float(hsn_taxable):,.2f} vs books "
                f"{float(books_net):,.2f}",
            },
            {
                "label": "No gaps in the invoice series",
                "ok": not docs["gaps"],
                "detail": (
                    "continuous"
                    if not docs["gaps"]
                    else f"missing: {', '.join(docs['gaps'][:5])}"
                ),
            },
        ]

        return {
            "gstin": self.company.gstin,
            "trade_name": self.company.trade_name,
            "period": filing_period(self.year, self.month),
            "period_label": f"{self.start:%B %Y}",
            "period_start": self.start,
            "period_end": self.end,
            # Both returns are due in the month after the period: GSTR-1 on
            # the 11th, GSTR-3B on the 20th.
            "due_dates": {
                "gstr1": (self.end + dt.timedelta(days=1)).replace(day=11),
                "gstr3b": (self.end + dt.timedelta(days=1)).replace(day=20),
            },
            "sections": [
                {
                    "code": "B2B",
                    "label": "Supplies to registered buyers",
                    "table": "4A",
                    "counterparties": len(payload["b2b"]),
                    "documents": sum(len(r["inv"]) for r in payload["b2b"]),
                    "taxable": float(b2b_taxable),
                },
                {
                    "code": "B2CL",
                    "label": "Interstate B2C above "
                    f"Rs {self.settings.b2cl_threshold:,}",
                    "table": "5A",
                    "counterparties": len(payload["b2cl"]),
                    "documents": sum(len(r["inv"]) for r in payload["b2cl"]),
                    "taxable": float(b2cl_taxable),
                },
                {
                    "code": "B2CS",
                    "label": "Other B2C, summarised",
                    "table": "7",
                    "counterparties": len(payload["b2cs"]),
                    "documents": len(payload["b2cs"]),
                    "taxable": float(b2cs_taxable),
                },
                {
                    "code": "CDNR",
                    "label": "Credit notes to registered buyers",
                    "table": "9B",
                    "counterparties": len(payload["cdnr"]),
                    "documents": sum(len(r["nt"]) for r in payload["cdnr"]),
                    "taxable": -float(cdnr_taxable),
                },
                {
                    "code": "HSN",
                    "label": "HSN summary",
                    "table": "12",
                    "counterparties": 0,
                    "documents": len(payload["hsn"]["data"]),
                    "taxable": float(hsn_taxable),
                },
            ],
            "totals": {
                "invoices": len(invoices),
                "credit_notes": len(notes),
                "taxable": float(books_net),
                "cgst": float(q2(
                    sum((Decimal(str(i.cgst_total)) for i in invoices), ZERO)
                    - sum((Decimal(str(n.cgst_total)) for n in notes), ZERO)
                )),
                "sgst": float(q2(
                    sum((Decimal(str(i.sgst_total)) for i in invoices), ZERO)
                    - sum((Decimal(str(n.sgst_total)) for n in notes), ZERO)
                )),
                "igst": float(q2(
                    sum((Decimal(str(i.igst_total)) for i in invoices), ZERO)
                    - sum((Decimal(str(n.igst_total)) for n in notes), ZERO)
                )),
            },
            "checks": checks,
            "gaps": docs["gaps"],
        }


def build_json(db: Session, year: int, month: int) -> dict:
    return Gstr1Builder(db, year, month).build()


def build_summary(db: Session, year: int, month: int) -> dict:
    return Gstr1Builder(db, year, month).summary()


def build_csv(db: Session, year: int, month: int, section: str) -> str:
    """One section as CSV, laid out like the offline tool's sheets."""
    builder = Gstr1Builder(db, year, month)
    payload = builder.build()
    section = section.lower()

    rows: list[list] = []
    if section == "b2b":
        rows.append([
            "GSTIN/UIN of Recipient", "Invoice Number", "Invoice date",
            "Invoice Value", "Place Of Supply", "Reverse Charge",
            "Invoice Type", "Rate", "Taxable Value",
            "Integrated Tax", "Central Tax", "State/UT Tax", "Cess",
        ])
        for party in payload["b2b"]:
            for invoice in party["inv"]:
                for item in invoice["itms"]:
                    d = item["itm_det"]
                    rows.append([
                        party["ctin"], invoice["inum"], invoice["idt"],
                        invoice["val"], invoice["pos"], invoice["rchrg"],
                        "Regular", d["rt"], d["txval"],
                        d.get("iamt", 0), d.get("camt", 0), d.get("samt", 0), 0,
                    ])
    elif section == "b2cl":
        rows.append([
            "Invoice Number", "Invoice date", "Invoice Value",
            "Place Of Supply", "Rate", "Taxable Value", "Cess",
        ])
        for party in payload["b2cl"]:
            for invoice in party["inv"]:
                for item in invoice["itms"]:
                    d = item["itm_det"]
                    rows.append([
                        invoice["inum"], invoice["idt"], invoice["val"],
                        party["pos"], d["rt"], d["txval"], 0,
                    ])
    elif section == "b2cs":
        rows.append([
            "Type", "Place Of Supply", "Rate", "Taxable Value",
            "Integrated Tax", "Central Tax", "State/UT Tax", "Cess",
        ])
        for row in payload["b2cs"]:
            rows.append([
                row["sply_ty"], row["pos"], row["rt"], row["txval"],
                row.get("iamt", 0), row.get("camt", 0), row.get("samt", 0), 0,
            ])
    elif section == "cdnr":
        rows.append([
            "GSTIN/UIN of Recipient", "Note Number", "Note Date", "Note Type",
            "Place Of Supply", "Invoice Number", "Invoice Date", "Note Value",
            "Rate", "Taxable Value", "Integrated Tax", "Central Tax",
            "State/UT Tax", "Cess",
        ])
        for party in payload["cdnr"]:
            for note in party["nt"]:
                for item in note["itms"]:
                    d = item["itm_det"]
                    rows.append([
                        party["ctin"], note["nt_num"], note["nt_dt"], "C",
                        note["pos"], note["inum"], note["idt"], note["val"],
                        d["rt"], d["txval"],
                        d.get("iamt", 0), d.get("camt", 0), d.get("samt", 0), 0,
                    ])
    elif section == "hsn":
        rows.append([
            "HSN", "Description", "UQC", "Total Quantity", "Rate",
            "Taxable Value", "Integrated Tax", "Central Tax",
            "State/UT Tax", "Cess",
        ])
        for row in payload["hsn"]["data"]:
            rows.append([
                row["hsn_sc"], row["desc"], row["uqc"], row["qty"], row["rt"],
                row["txval"], row["iamt"], row["camt"], row["samt"], 0,
            ])
    elif section == "docs":
        rows.append([
            "Nature of Document", "Sr. No. From", "Sr. No. To",
            "Total Number", "Cancelled",
        ])
        for det in payload["doc_issue"]["doc_det"]:
            for doc in det["docs"]:
                rows.append([
                    det.get("doc_typ", ""), doc["from"], doc["to"],
                    doc["totnum"], doc["cancel"],
                ])
    else:
        raise ValueError(
            "Section must be one of: b2b, b2cl, b2cs, cdnr, hsn, docs."
        )

    def cell(value) -> str:
        text = "" if value is None else str(value)
        if any(c in text for c in ',"\n'):
            return '"' + text.replace('"', '""') + '"'
        return text

    return "\r\n".join(",".join(cell(c) for c in row) for row in rows) + "\r\n"
