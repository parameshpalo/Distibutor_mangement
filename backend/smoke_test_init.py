"""Starting a real database: `python -m app.init`.

    python smoke_test_init.py

Needs no running server. Each case runs `app.init` in its own process against
a throwaway SQLite file, so the live database is never touched -- which is the
whole point of a script that tests a tool whose job is to create and destroy
databases.

What matters here is what init does *not* do: it must not invent a GSTIN, an
address or a rate card, because anything it writes ends up printed on a tax
invoice. So most of these assertions are about blanks being left blank.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).resolve().parent
passed, failed = [], []


def check(name: str, condition: bool, detail: str = ""):
    (passed if condition else failed).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{'  -> ' + detail if detail else ''}")


def run_init(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Forward slashes: a SQLAlchemy URL is a URL, not a Windows path.
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "app.init", *args],
        cwd=HERE, env=env, capture_output=True, text=True,
    )


def rows(db_path: Path, sql: str, args=()):
    # closing(), not just the connection's own context manager: that one
    # commits and leaves the handle open, which on Windows holds a lock that
    # stops the temporary directory being removed.
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        return conn.execute(sql, args).fetchall()


with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)

    print("=" * 72)
    print("1. A database with the firm's details given")
    print("=" * 72)
    db = workspace / "full.db"
    result = run_init(
        db, "--gstin", "21ABCDE1234F1Z5", "--name", "Test Agencies",
        "--prefix", "TA",
    )
    check("init succeeds", result.returncode == 0,
          (result.stderr or result.stdout).strip()[:120])
    if result.returncode == 0:
        check("it reports the catalogue it loaded",
              "products" in result.stdout, result.stdout.splitlines()[0])
        check("the home state is read off the GSTIN, not asked for",
              "Odisha" in result.stdout,
              [l for l in result.stdout.splitlines() if "state" in l][0])
        # The command line carries a name and a GSTIN; it cannot carry an
        # address, so init says so rather than filling one in.
        check("the address is still reported as needed",
              "address line1" in result.stdout and "pincode" in result.stdout,
              "address and PIN listed")
        check("the name and GSTIN are not in that list",
              "- legal name" not in result.stdout
              and "- gstin" not in result.stdout,
              "both taken from the command line")

        profile = rows(db, "SELECT legal_name, trade_name, gstin, state_code, "
                           "state_name, invoice_prefix FROM company_profile")
        check("one company profile, no more", len(profile) == 1, str(len(profile)))
        legal, trade, gstin, code, state, prefix = profile[0]
        check("the legal name is what was given", legal == "Test Agencies", legal)
        check("the trading name falls back to the legal name",
              trade == "Test Agencies", trade)
        check("the state code is the GSTIN's first two digits",
              code == "21" and gstin.startswith("21"), f"{code} / {gstin}")
        check("the state is named from that code", state == "Odisha", state)
        check("the invoice prefix is what was asked for", prefix == "TA", prefix)

        count = rows(db, "SELECT COUNT(*) FROM products")[0][0]
        check("the supplier's catalogue is loaded", count > 100, f"{count} SKUs")
        check("every SKU has a sellable price",
              rows(db, "SELECT COUNT(*) FROM products WHERE ptr IS NULL "
                       "OR ptr <= 0")[0][0] == 0,
              "no missing PTR")
        check("a sub-distributor never pays more than a shop",
              rows(db, "SELECT COUNT(*) FROM products WHERE ptd >= ptr")[0][0] == 0,
              "PTD below PTR throughout")

        rates = rows(db, "SELECT rate, effective_from, effective_to FROM gst_rates "
                         "WHERE hsn = '1905' ORDER BY effective_from")
        check("both biscuit slabs are present, so a back-dated bill is right",
              len(rates) == 2, str([r[0] for r in rates]))
        check("the current slab is open-ended",
              rates and rates[-1][2] is None, str(rates[-1] if rates else None))

        print()
        print("  -- and nothing has been traded yet --")
        for table in ("invoices", "stock_ledger", "retailers", "payments",
                      "orders", "beats", "purchases", "credit_notes"):
            count = rows(db, f"SELECT COUNT(*) FROM {table}")[0][0]
            check(f"no {table}", count == 0, str(count))

    print()
    print("=" * 72)
    print("2. With nothing given, nothing is invented")
    print("=" * 72)
    blank = workspace / "blank.db"
    result = run_init(blank)
    check("init still succeeds", result.returncode == 0,
          (result.stderr or result.stdout).strip()[:120])
    if result.returncode == 0:
        check("it says what is still needed",
              "Still blank" in result.stdout, "lists the blanks")
        check("it names the GSTIN as missing",
              "gstin" in result.stdout, "gstin listed")
        check("it does not claim a home state",
              "UNKNOWN" in result.stdout, "UNKNOWN")
        legal, gstin, city, state = rows(
            blank,
            "SELECT legal_name, gstin, city, state_name FROM company_profile",
        )[0]
        check("no name was made up", legal == "", repr(legal))
        check("no GSTIN was made up", gstin == "", repr(gstin))
        check("no address was made up", city == "" and state == "",
              f"{city!r} / {state!r}")
        check("the catalogue is still loaded, since it is the supplier's",
              rows(blank, "SELECT COUNT(*) FROM products")[0][0] > 100,
              "products present")

    print()
    print("=" * 72)
    print("3. It refuses to destroy data by accident")
    print("=" * 72)
    again = run_init(blank)
    check("a second run on a populated database is refused",
          again.returncode != 0, f"exit {again.returncode}")
    check("the refusal says what is in the way",
          "already data" in (again.stdout + again.stderr),
          (again.stdout + again.stderr).strip().splitlines()[0][:80])
    check("the refusal says how to go ahead anyway",
          "--force" in (again.stdout + again.stderr), "--force named")
    check("nothing was dropped by the refused run",
          rows(blank, "SELECT COUNT(*) FROM products")[0][0] > 100,
          "catalogue intact")

    forced = run_init(blank, "--force", "--gstin", "36ABCDE1234F1Z5",
                      "--name", "Second Go")
    check("--force replaces it", forced.returncode == 0,
          (forced.stderr or "").strip()[:100])
    if forced.returncode == 0:
        legal, code, state = rows(
            blank, "SELECT legal_name, state_code, state_name FROM company_profile"
        )[0]
        check("the new details took", legal == "Second Go", legal)
        check("and the new state with them", code == "36" and state == "Telangana",
              f"{code} {state}")
        check("still exactly one profile after a rebuild",
              rows(blank, "SELECT COUNT(*) FROM company_profile")[0][0] == 1)

    print()
    print("=" * 72)
    print("4. A malformed GSTIN is caught before anything is written")
    print("=" * 72)
    bad = workspace / "bad.db"
    result = run_init(bad, "--gstin", "21ABC")
    check("a short GSTIN is refused", result.returncode == 2,
          f"exit {result.returncode}")
    check("the message says how long a GSTIN is",
          "15 characters" in result.stderr, result.stderr.strip()[:80])
    check("no database was created", not bad.exists() or not rows(
        bad, "SELECT name FROM sqlite_master WHERE name='company_profile'"),
        "nothing written")

print()
print("=" * 72)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")
for name in failed:
    print(f"  FAILED: {name}")
print("=" * 72)
sys.exit(1 if failed else 0)
