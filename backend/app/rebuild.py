"""Drop every table and build the schema again.

There is no Alembic yet, so a schema change is applied by rebuilding. That is
acceptable before go-live and destroys the business after it, which is the whole
reason this script exists rather than a bare `drop_all` call in a shell one-liner.

Some schema changes cannot be made any other way on SQLite. `stock_ledger` has a
`CHECK` constraint listing the valid movement reasons (`ck_ledger_reason`), and
SQLite cannot alter a constraint in place: an existing file keeps the old list and
rejects a new reason at flush time with an opaque IntegrityError. Adding a reason
therefore means rebuilding.

The guard: if the database already holds invoices, this refuses unless you pass
`--force` and type the invoice count back. Not a confirmation prompt for the sake
of one, but because by then the file is the only record of money owed.

    python -m app.rebuild                 # rebuild empty, keep masters only
    python -m app.rebuild --demo          # rebuild and seed the demo dataset
    python -m app.rebuild --demo --force  # same, over the top of real invoices
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

from sqlalchemy import MetaData, func, inspect, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine


def _sqlite_path() -> Path | None:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        return None
    return Path(url.replace("sqlite:///", ""))


def existing_counts() -> dict[str, int]:
    """What is in there now, in the terms that matter: money and documents.

    Returns an empty dict when nothing is there yet, so a first run on a fresh
    file does not have to be special-cased by the caller.

    Each table is checked on its own rather than inferring from one of them.
    An interrupted rebuild leaves some tables dropped and others not, and this
    is the one tool that can repair that state -- so it must not be the thing
    that falls over on it.
    """
    inspector = inspect(engine)
    # Imported here: on a fresh database the models must be registered before
    # create_all, but reading them is only meaningful once tables exist.
    from .models import CreditNote, Invoice, Payment, Retailer

    counts = {}
    with SessionLocal() as db:
        for label, model in (
            ("invoices", Invoice),
            ("payments", Payment),
            ("credit notes", CreditNote),
            ("parties", Retailer),
        ):
            if not inspector.has_table(model.__tablename__):
                continue
            counts[label] = int(
                db.execute(select(func.count(model.id))).scalar_one() or 0
            )
    return counts


def backup_sqlite() -> Path | None:
    """Copy the file aside before destroying it.

    Not a backup strategy — there isn't one yet — but it makes this script
    survivable if it is run on the wrong database.
    """
    path = _sqlite_path()
    if path is None or not path.exists():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.before-rebuild-{stamp}{path.suffix}")
    shutil.copy2(path, target)
    return target


def rebuild() -> None:
    """Drop and recreate every table. The caller has already decided it is safe.

    The live schema is reflected rather than taken from the models, because
    those are two different things once a table has been removed from the code.
    `Base.metadata.drop_all` only drops tables it still knows about, so a table
    that was deleted from `models.py` survives in the file -- and its foreign
    keys then refuse the drop of a table that *is* still in the models, with a
    bare "FOREIGN KEY constraint failed" naming the wrong table.

    Reflection drops what is actually there, in dependency order, which is the
    only version of this that keeps working as the schema moves.
    """
    live = MetaData()
    live.reflect(bind=engine)
    live.drop_all(bind=engine)
    Base.metadata.create_all(engine)


def seed_masters(db: Session) -> dict[str, int]:
    """The rows the app cannot work without, and nothing else.

    No parties, no stock, no invoices. Reuses the seed module's own builders so
    there is one definition of a company profile and a GST rate, not two.

    Number series are not seeded: `numbering._next_sequence` creates the row for
    a kind and financial year the first time one is asked for.
    """
    from . import seed as demo

    company = demo.seed_company(db)
    demo.seed_gst_rates(db)
    products = demo.seed_products(db)
    db.commit()
    return {"company": 1 if company else 0, "products": len(products)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Drop every table and build the schema again."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="seed the full demo dataset afterwards instead of masters only",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="proceed even though the database already holds invoices",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="skip copying the SQLite file aside first",
    )
    args = parser.parse_args()

    counts = existing_counts()
    if counts:
        print("This database currently holds:")
        for label, n in counts.items():
            print(f"  {label:14} {n:>7,}")

    invoices = counts.get("invoices", 0)
    if invoices and not args.force:
        print()
        print(f"Refusing to rebuild: there are {invoices:,} invoices in here.")
        print("Rebuilding drops them. If that is genuinely what you want, pass")
        print("--force. If this is the live database, do not.")
        sys.exit(1)

    if not args.no_backup:
        saved = backup_sqlite()
        if saved is not None:
            print(f"\nCopied the old file to {saved.name}")

    rebuild()
    print("Schema rebuilt.")

    if args.demo:
        from . import seed as demo

        result = demo.run()
        width = max(len(k) for k in result)
        print()
        for key, value in result.items():
            shown = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
            print(f"{key:<{width}}  {shown}")
    else:
        with SessionLocal() as db:
            masters = seed_masters(db)
        print()
        print(f"company profile   {masters['company']}")
        print(f"products          {masters['products']:,}")
        print("No parties, stock or invoices. Enter your firm's details under Setup.")


if __name__ == "__main__":
    main()
