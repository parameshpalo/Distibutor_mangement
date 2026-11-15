"""Start a real database: schema, the firm's own details, the catalogue.

    python -m app.init --gstin 21ABCDE1234F1Z5 --name "Name of the firm"
    python -m app.init --force          # replace an existing empty database

This is how the app is started for actual trading, as against `app.seed`,
which fills it with a demonstration. It writes:

  * the schema;
  * one company profile -- the firm's own details, printed on every invoice;
  * the GST rates for HSN 1905 (biscuits), both slabs, so a back-dated bill
    is taxed at the rate that applied on its own date;
  * the supplier's catalogue of SKUs, with PTR and PTD derived the same way
    the demo derives them.

It writes no transactions at all: no stock, no customers, no bills. The first
real entry is a goods-received note, because nothing can be sold before
something has arrived.

**Nothing here is invented.** Anything not given on the command line is left
blank and shown as "needs filling" on the My firm page, rather than filled
with a plausible-looking value that would then be printed on a tax invoice.
The two prices the supplier's sheet does not state (PTR and PTD) are derived
arithmetically and flagged on the Products page as figures to confirm.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from decimal import Decimal

from sqlalchemy import MetaData, func, inspect, select
from sqlalchemy.orm import Session

from .database import Base, engine
from .models import CompanyProfile, GstRate, Product
# Borrowed from the demo seed rather than copied: PTR and PTD are derived
# there, and two derivations that could drift apart would be worse than
# this one import.
from .seed import seed_products

# The state a GSTIN belongs to is its first two digits. This is the actual
# rule, not a lookup we maintain, which is why only the ones we can name are
# listed -- an unknown code is reported as such rather than guessed.
STATE_NAMES = {
    "21": "Odisha",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "19": "West Bengal",
    "20": "Jharkhand",
    "22": "Chhattisgarh",
    "33": "Tamil Nadu",
    "29": "Karnataka",
    "27": "Maharashtra",
    "24": "Gujarat",
    "09": "Uttar Pradesh",
    "07": "Delhi",
}


def gst_rates_1905() -> list[GstRate]:
    """Both slabs biscuits have sat in, so a dated lookup works.

    The second rate is the one in force. Confirm it against the current
    notification before billing: a wrong rate here is a wrong rate on every
    invoice and in the GSTR-1 return.
    """
    return [
        GstRate(
            hsn="1905",
            rate=Decimal("18"),
            effective_from=dt.date(2017, 7, 1),
            effective_to=dt.date(2025, 9, 21),
            note="Pre-rationalisation slab for biscuits",
        ),
        GstRate(
            hsn="1905",
            rate=Decimal("5"),
            effective_from=dt.date(2025, 9, 22),
            effective_to=None,
            note="Rate effective from the Sept-2025 GST rationalisation. "
            "Confirm against the current notification before go-live.",
        ),
    ]


def existing_rows() -> dict[str, int]:
    """What is already in the file, table by table.

    Checked per table rather than in one query, so a half-built database
    still reports instead of raising.
    """
    inspector = inspect(engine)
    counts: dict[str, int] = {}
    with Session(engine) as db:
        for model in (CompanyProfile, Product):
            if not inspector.has_table(model.__tablename__):
                continue
            counts[model.__tablename__] = db.execute(
                select(func.count()).select_from(model)
            ).scalar_one()
    return counts


def build(
    *,
    gstin: str = "",
    legal_name: str = "",
    trade_name: str = "",
    invoice_prefix: str = "INV",
    force: bool = False,
) -> dict:
    counts = existing_rows()
    if any(counts.values()) and not force:
        raise SystemExit(
            "There is already data in this database: "
            + ", ".join(f"{t} {n}" for t, n in counts.items() if n)
            + ".\nUse --force to replace it, which deletes everything."
        )

    if force:
        # Drop what is actually in the file, not what the models describe, so
        # tables left behind by an earlier version go too.
        live = MetaData()
        live.reflect(bind=engine)
        live.drop_all(bind=engine)
    Base.metadata.create_all(engine)

    state_code = gstin[:2] if len(gstin) >= 2 else ""
    with Session(engine) as db:
        db.add(CompanyProfile(
            legal_name=legal_name,
            trade_name=trade_name or legal_name,
            gstin=gstin,
            address_line1="",
            city="",
            state_name=STATE_NAMES.get(state_code, ""),
            state_code=state_code,
            pincode="",
            invoice_prefix=invoice_prefix,
        ))
        db.add_all(gst_rates_1905())
        db.flush()
        products = seed_products(db)
        db.commit()

        blanks = [
            field
            for field in (
                "legal_name", "gstin", "address_line1", "city",
                "state_name", "state_code", "pincode",
            )
            if not getattr(db.execute(select(CompanyProfile)).scalar_one(), field)
        ]

    return {
        "products": len(products),
        "gst_rates": 2,
        "state": STATE_NAMES.get(state_code, "UNKNOWN"),
        "needs_filling": blanks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start an empty database for real trading."
    )
    parser.add_argument("--gstin", default="", help="the firm's own GSTIN")
    parser.add_argument("--name", default="", help="legal name of the firm")
    parser.add_argument(
        "--trade-name", default="", help="the name it trades under, if different"
    )
    parser.add_argument(
        "--prefix", default="INV",
        help="invoice series prefix, at most 6 characters (default INV)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="delete everything already in the database first",
    )
    args = parser.parse_args()

    if args.gstin and len(args.gstin) != 15:
        print(
            f"A GSTIN is 15 characters; '{args.gstin}' is {len(args.gstin)}.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    result = build(
        gstin=args.gstin,
        legal_name=args.name,
        trade_name=args.trade_name,
        invoice_prefix=args.prefix,
        force=args.force,
    )

    print(f"products        {result['products']}")
    print(f"gst rates       {result['gst_rates']} (HSN 1905)")
    print(f"home state      {result['state']}")
    if result["needs_filling"]:
        print()
        print("Still blank, and needed before the first bill is printed:")
        for field in result["needs_filling"]:
            print(f"  - {field.replace('_', ' ')}")
        print("Fill these in on Setup -> My firm.")
    else:
        print("company profile complete")


if __name__ == "__main__":
    main()
