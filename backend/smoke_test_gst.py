"""End-to-end check of the GSTR-1 return.

Run against a live server:  python smoke_test_gst.py [base_url]

The important assertions are the arithmetic ones: that the return reconciles
to the books, and that each section carries what belongs in it and nothing
that does not.

E-invoicing and e-way bills were removed from the app. Section 4 now asserts
their absence rather than their behaviour, so neither can creep back in
unnoticed.
"""

import datetime as dt
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8095"

# The last complete month, which is the one you would actually file. Derived
# rather than hardcoded: the demo's history now follows the calendar, so a
# fixed month would drift out of the data and the suite would start passing
# on an empty return.
_first_of_this_month = dt.date.today().replace(day=1)
_last_complete = _first_of_this_month - dt.timedelta(days=1)
YEAR, MONTH = _last_complete.year, _last_complete.month
passed, failed = [], []


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            if not raw:
                return response.status, None
            ctype = response.headers.get("Content-Type", "")
            if "json" in ctype:
                return response.status, json.loads(raw)
            return response.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except Exception:
            return error.code, raw.decode(errors="replace")


def check(name: str, condition: bool, detail: str = ""):
    (passed if condition else failed).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{'  -> ' + detail if detail else ''}")


period = f"year={YEAR}&month={MONTH}"

print("=" * 72)
print("1. GSTR-1 reconciles to the books")
print("=" * 72)
status, summary = call("GET", f"/api/gst/gstr1?{period}")
check("summary builds", status == 200, str(status))
if status == 200:
    by_code = {s["code"]: s for s in summary["sections"]}
    sections_net = (
        by_code["B2B"]["taxable"]
        + by_code["B2CL"]["taxable"]
        + by_code["B2CS"]["taxable"]
        + by_code["CDNR"]["taxable"]
    )
    check("sections sum to the books' net taxable",
          abs(sections_net - summary["totals"]["taxable"]) < 1.0,
          f"{sections_net:,.2f} vs {summary['totals']['taxable']:,.2f}")
    check("HSN summary agrees too",
          abs(by_code["HSN"]["taxable"] - summary["totals"]["taxable"]) < 1.0,
          f"{by_code['HSN']['taxable']:,.2f}")
    check("reconciliation check passes",
          next(c for c in summary["checks"]
               if "reconcile" in c["label"])["ok"])
    check("no gaps in the document series",
          next(c for c in summary["checks"] if "gaps" in c["label"])["ok"],
          next(c for c in summary["checks"] if "gaps" in c["label"])["detail"])
    check("GSTR-1 due on the 11th",
          summary["due_dates"]["gstr1"].endswith("-11"),
          summary["due_dates"]["gstr1"])
    check("GSTR-3B due on the 20th",
          summary["due_dates"]["gstr3b"].endswith("-20"),
          summary["due_dates"]["gstr3b"])
    check("period code is MMYYYY", summary["period"] == f"{MONTH:02d}{YEAR}",
          summary["period"])

print()
print("=" * 72)
print("2. Each section carries only what belongs in it")
print("=" * 72)
status, payload = call("GET", f"/api/gst/gstr1/json?{period}")
check("JSON builds", status == 200, str(status))
if status == 200:
    check("every B2B party has a GSTIN",
          all(len(p["ctin"]) == 15 for p in payload["b2b"]),
          f"{len(payload['b2b'])} parties")
    check("B2B documents carry a place of supply",
          all(inv["pos"] for p in payload["b2b"] for inv in p["inv"]))
    check("B2B items are rate-wise",
          all(inv["itms"] for p in payload["b2b"] for inv in p["inv"]))

    intra = [r for r in payload["b2cs"] if r["sply_ty"] == "INTRA"]
    inter = [r for r in payload["b2cs"] if r["sply_ty"] == "INTER"]
    check("intrastate B2CS rows carry CGST and SGST, not IGST",
          all("camt" in r and "samt" in r and "iamt" not in r for r in intra),
          f"{len(intra)} intra rows")
    check("interstate B2CS rows carry IGST only",
          all("iamt" in r and "camt" not in r for r in inter),
          f"{len(inter)} inter rows")

    check("dates are dd-mm-yyyy",
          all(len(inv["idt"].split("-")) == 3 and len(inv["idt"]) == 10
              for p in payload["b2b"] for inv in p["inv"]))
    check("credit notes are typed C",
          all(n["ntty"] == "C" for p in payload["cdnr"] for n in p["nt"]),
          f"{sum(len(p['nt']) for p in payload['cdnr'])} notes")
    check("CDNR notes reference their original invoice",
          all(n["inum"] for p in payload["cdnr"] for n in p["nt"]))
    check("HSN codes are present",
          all(r["hsn_sc"] for r in payload["hsn"]["data"]),
          f"{len(payload['hsn']['data'])} HSN rows")
    check("document series reported", bool(payload["doc_issue"]["doc_det"]),
          f"{len(payload['doc_issue']['doc_det'])} series")

print()
print("=" * 72)
print("3. CSV exports")
print("=" * 72)
for section in ("b2b", "b2cs", "cdnr", "hsn", "docs"):
    status, body = call("GET", f"/api/gst/gstr1/csv?{period}&section={section}")
    lines = (body or "").strip().splitlines()
    check(f"{section.upper()} CSV exports", status == 200 and len(lines) >= 1,
          f"{len(lines)} rows")
status, body = call("GET", f"/api/gst/gstr1/csv?{period}&section=nonsense")
check("unknown section rejected", status == 422, str(status))

print()
print("=" * 72)
print("4. e-invoicing and e-way bills are out of the app")
print("=" * 72)
# Both were removed deliberately. E-invoicing applies above a turnover this
# firm is well under, and e-way bills are raised on the government portal.
# These assertions exist so a future change cannot quietly bring back a
# locally computed IRN, which would never be valid for filing.
for path in ("/api/gst/einvoice/status", "/api/gst/eway"):
    status, _ = call("GET", path)
    check(f"{path} is gone", status == 404, str(status))

status, summary = call("GET", f"/api/gst/gstr1?year={YEAR}&month={MONTH}")
if status == 200:
    check("the return no longer checks for IRNs",
          not any("IRN" in c["label"] for c in summary["checks"]),
          f"{len(summary['checks'])} checks, none about IRNs")
    check("no missing-IRN count in the payload",
          "missing_irn_count" not in summary and "missing_irn" not in summary,
          "absent")
    check("the remaining checks all pass",
          all(c["ok"] for c in summary["checks"]),
          "; ".join(c["label"] for c in summary["checks"] if not c["ok"]) or "all ok")

status, invoices = call("GET", "/api/invoices?limit=1")
if status == 200 and invoices:
    status, detail = call("GET", f"/api/invoices/{invoices[0]['id']}")
    check("an invoice carries no IRN field", "irn" not in detail, "absent")
    check("an invoice carries no salesman", "salesman_name" not in detail,
          "absent")

print("=" * 72)
print("7. Nothing earlier broke")
print("=" * 72)
status, dash = call("GET", "/api/dashboard")
check("dashboard still loads", status == 200, str(status))
if status == 200:
    rec = dash["receivables"]
    bucket_sum = round(sum(b["amount"] for b in rec["buckets"]), 2)
    check("ageing still ties", abs(bucket_sum - rec["total"]) < 0.5,
          f"{bucket_sum} vs {rec['total']}")
status, _ = call("GET", "/api/stock")
check("stock still loads", status == 200, str(status))

print()
print("=" * 72)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")
for name in failed:
    print(f"  FAILED: {name}")
print("=" * 72)
sys.exit(1 if failed else 0)
