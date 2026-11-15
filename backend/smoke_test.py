"""End-to-end check of the write paths and the business rules.

Run against a live server:  python smoke_test.py [base_url]

Exercises goods inward, pricing preview, invoicing, the credit-limit stop,
the stock shortfall stop, payment allocation across invoices, and confirms
the stock ledger and receivables move by exactly the right amounts. Also
checks that one sale prints two ways: the firm's tax invoice and the
shop's plain cash memo.
"""

import datetime as dt
import io
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8095"
passed, failed = [], []


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            if not raw:
                return response.status, None
            if "json" not in response.headers.get("Content-Type", ""):
                return response.status, {"bytes": len(raw)}
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except Exception:
            return error.code, raw.decode(errors="replace")


def check(name: str, condition: bool, detail: str = ""):
    (passed if condition else failed).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{'  -> ' + detail if detail else ''}")


print("=" * 72)
print("1. Goods inward (GRN)")
print("=" * 72)
_, products = call("GET", "/api/products")
_, stock_before = call("GET", "/api/stock")
product = products[0]
batch_no = f"SMOKE{dt.date.today():%y%m%d}"

status, grn = call(
    "POST",
    "/api/purchases",
    {
        "supplier_name": "Smoke Test Depot",
        "company_invoice_no": "ST/0001",
        "company_invoice_date": "2026-10-20",
        "received_on": "2026-10-23",
        "lines": [
            {
                "product_id": product["id"],
                "batch_no": batch_no,
                "mfg_date": "2026-10-01",
                "cases": 10,
                "loose_pieces": 5,
            }
        ],
    },
)
check("GRN created", status == 201, str(status))
if status == 201:
    expected_pieces = 10 * product["pieces_per_case"] + 5
    line = grn["lines"][0]
    check("GRN quantity = cases x pack + loose", line["qty_pieces"] == expected_pieces,
          f"{line['qty_pieces']} vs {expected_pieces}")
    check("GRN totals add up",
          abs(line["taxable"] + line["tax_amount"] - line["line_total"]) < 0.01)
    check("GRN expiry derived from shelf life", bool(line["expiry_date"]),
          line["expiry_date"])
    _, stock_after = call("GET", "/api/stock")
    delta = stock_after["totals"]["pieces"] - stock_before["totals"]["pieces"]
    check("stock rose by exactly the received quantity", delta == expected_pieces,
          f"{delta} vs {expected_pieces}")

print()
print("=" * 72)
print("2. Expired stock is refused at inward")
print("=" * 72)
status, body = call(
    "POST",
    "/api/purchases",
    {
        "supplier_name": "Smoke Test Depot",
        "company_invoice_no": "ST/0002",
        "company_invoice_date": "2026-10-20",
        "received_on": "2026-10-23",
        "lines": [{
            "product_id": product["id"],
            "batch_no": "SMOKEOLD",
            "mfg_date": "2025-01-01",
            "expiry_date": "2026-09-01",
            "cases": 1,
        }],
    },
)
check("already-expired batch rejected", status == 422, str(status))

print()
print("=" * 72)
print("3. Pricing preview")
print("=" * 72)
_, retailers = call("GET", "/api/retailers")
local = next(r for r in retailers if r["state_code"] == "36" and r["credit_limit"] > 100000)
far = next(r for r in retailers if r["state_code"] != "36")

status, preview = call("POST", "/api/invoices/preview", {
    "retailer_id": local["id"],
    "lines": [{"product_id": product["id"], "cases": 2}],
})
check("preview returns totals", status == 200, str(status))
if status == 200:
    t = preview["totals"]
    check("intrastate splits into CGST + SGST",
          t["cgst_total"] > 0 and t["sgst_total"] > 0 and t["igst_total"] == 0)
    check("CGST equals SGST", abs(t["cgst_total"] - t["sgst_total"]) < 0.01)
    check("grand total is a whole rupee", abs(t["grand_total"] - round(t["grand_total"])) < 0.001,
          str(t["grand_total"]))
    check("total = taxable + tax + round off",
          abs(t["taxable_total"] + t["cgst_total"] + t["sgst_total"]
              + t["round_off"] - t["grand_total"]) < 0.01)
    check("amount in words present", preview["amount_in_words"].startswith("Rupees"),
          preview["amount_in_words"])
    check("FEFO picked a batch", len(preview["lines"][0]["batches"]) >= 1)

status, far_preview = call("POST", "/api/invoices/preview", {
    "retailer_id": far["id"],
    "lines": [{"product_id": product["id"], "cases": 1}],
})
if status == 200:
    t = far_preview["totals"]
    check("interstate charges IGST only",
          t["igst_total"] > 0 and t["cgst_total"] == 0 and t["sgst_total"] == 0)

print()
print("=" * 72)
print("4. Raising an invoice moves stock")
print("=" * 72)
_, stock_pre = call("GET", "/api/stock")
status, invoice = call("POST", "/api/invoices", {
    "retailer_id": local["id"],
    "lines": [
        {"product_id": product["id"], "cases": 2},
        {"product_id": products[1]["id"], "cases": 1, "discount_pct": 5},
        {"product_id": products[2]["id"], "cases": 1, "is_free": True},
    ],
    "note": "smoke test",
})
check("invoice created", status == 201, str(status) if status != 201 else invoice["invoice_no"])
if status == 201:
    check("invoice number fits the IRN 16-char limit",
          len(invoice["invoice_no"]) <= 16, invoice["invoice_no"])
    check("due date respects credit days", invoice["due_date"] >= invoice["invoice_date"])
    free_line = next(l for l in invoice["lines"] if l["is_free"])
    check("free scheme line carries qty but no value",
          free_line["qty_pieces"] > 0 and free_line["taxable"] == 0)
    check("discount applied on the second line",
          next(l for l in invoice["lines"] if l["discount"] > 0) is not None)
    check("header taxable = sum of lines",
          abs(invoice["taxable_total"] - sum(l["taxable"] for l in invoice["lines"])) < 0.01)
    check("balance equals total when unpaid",
          abs(invoice["balance"] - invoice["grand_total"]) < 0.01)
    check("every line shows its batch", all(l["batches"] for l in invoice["lines"]))

    sold = sum(l["qty_pieces"] for l in invoice["lines"])
    _, stock_post = call("GET", "/api/stock")
    drop = stock_pre["totals"]["pieces"] - stock_post["totals"]["pieces"]
    check("stock fell by exactly the invoiced quantity", drop == sold, f"{drop} vs {sold}")

    status_pdf, _ = call("GET", f"/api/invoices/{invoice['id']}/pdf")
    check("invoice PDF renders", status_pdf == 200, str(status_pdf))

print()
print("=" * 72)
print("5. The credit limit warns; it does not stop the bill")
print("=" * 72)
# The limit used to raise a 409 the biller had to override. It no longer
# does: the bill at a shop counter is written with the goods already handed
# over, so the warning has to arrive on the preview, before the decision --
# not as a refusal after it.
small = min(
    (r for r in retailers if r["credit_limit"] > 0),
    key=lambda r: r["credit_limit"],
)
# Enough to clear the credit limit, but still inside what the godown holds,
# so this tests the credit rule rather than the stock rule.
_, stock_now = call("GET", f"/api/stock?search={product['sku_code']}")
available = stock_now["items"][0]["pieces"] if stock_now["items"] else 0
per_case = product["pieces_per_case"]
cases = int(small["credit_limit"] / (product["ptr"] * per_case)) + 3
cases = min(cases, max(available // per_case - 1, 1))

status, pv = call("POST", "/api/invoices/preview", {
    "retailer_id": small["id"],
    "lines": [{"product_id": product["id"], "cases": cases}],
})
check("the preview prices an over-limit bill", status == 200, str(status))
if status == 200:
    credit = pv["credit"]
    check("the preview warns that the limit would be passed",
          credit["would_exceed"] is True,
          f"{credit['after_this_bill']:,.0f} against a limit of "
          f"{credit['limit']:,.0f}")
    check("it says what is already owed and what the bill would make it",
          credit["outstanding"] >= 0
          and abs(credit["after_this_bill"]
                  - (credit["outstanding"] + pv["totals"]["grand_total"])) < 0.01,
          f"owes {credit['outstanding']:,.0f}")

status, body = call("POST", "/api/invoices", {
    "retailer_id": small["id"],
    "lines": [{"product_id": product["id"], "cases": cases}],
})
check("the over-limit bill goes through anyway", status == 201,
      f"status {status}, {cases} cases vs limit Rs {small['credit_limit']:,.0f}")

status, after = call("POST", "/api/invoices/preview", {
    "retailer_id": small["id"],
    "lines": [{"product_id": product["id"], "cases": 1}],
})
if status == 200:
    check("the next preview shows the larger balance",
          after["credit"]["outstanding"] > 0
          and after["credit"]["would_exceed"] is True,
          f"now owes {after['credit']['outstanding']:,.0f}")

print()
print("=" * 72)
print("6. Stock shortfall stops the bill")
print("=" * 72)
status, body = call("POST", "/api/invoices", {
    "retailer_id": local["id"],
    "lines": [{"product_id": product["id"], "cases": 99999}],
})
check("impossible quantity refused with 409", status == 409, str(status))
check("message says what is available", "available" in json.dumps(body).lower(),
      json.dumps(body)[:120])

status, pv = call("POST", "/api/invoices/preview", {
    "retailer_id": local["id"],
    "lines": [{"product_id": product["id"], "cases": 99999}],
})
check("preview warns instead of failing", status == 200, str(status))
if status == 200:
    check("preview names the shortfall", len(pv["stock_warnings"]) == 1,
          str(pv["stock_warnings"])[:120])

print()
print("=" * 72)
print("7. Collections and allocation")
print("=" * 72)
_, open_bills = call("GET", f"/api/retailers/{local['id']}/open-invoices")
check("retailer has open invoices", len(open_bills) > 0, f"{len(open_bills)} open")
if open_bills:
    oldest_two = open_bills[:2]
    pay_amount = round(sum(b["balance"] for b in oldest_two), 2)
    status, payment = call("POST", "/api/payments", {
        "retailer_id": local["id"],
        "amount": pay_amount,
        "mode": "upi",
        "reference": "SMOKEUPI1",
    })
    check("payment recorded", status == 201, str(status))
    if status == 201:
        check("auto-allocated oldest first",
              len(payment["allocations"]) >= 1
              and payment["allocations"][0]["invoice_id"] == oldest_two[0]["id"])
        allocated = round(sum(a["amount"] for a in payment["allocations"]), 2)
        check("allocations do not exceed the payment", allocated <= pay_amount + 0.01,
              f"{allocated} vs {pay_amount}")
        _, after = call("GET", f"/api/invoices/{oldest_two[0]['id']}")
        check("invoice balance reduced to zero", abs(after["balance"]) < 0.01,
              str(after["balance"]))

    status, body = call("POST", "/api/payments", {
        "retailer_id": local["id"],
        "amount": 100,
        "mode": "cash",
        "allocations": [{"invoice_id": oldest_two[0]["id"], "amount": 100}],
    })
    check("cannot allocate to a settled invoice", status == 422, str(status))

print()
print("=" * 72)
print("8. Dashboard still consistent")
print("=" * 72)
status, dash = call("GET", "/api/dashboard")
check("dashboard loads", status == 200, str(status))
if status == 200:
    m, q = dash["month"], dash["quarter"]
    check("month is billed value, not a target", m["value"] > 0, str(m["value"]))
    check("month reports cases too", m["cases"] > 0, f"{m['cases']} cases")
    check("the quarter contains the month", q["value"] >= m["value"],
          f"Q {q['value']} vs M {m['value']}")
    check("the trend ends on the current month",
          dash["trend"][-1]["month_start"] == m["period_start"],
          f"{dash['trend'][-1]['month_start']} vs {m['period_start']}")
    check("the trend's last month matches the month figure",
          abs(dash["trend"][-1]["value"] - m["value"]) < 0.5,
          f"{dash['trend'][-1]['value']} vs {m['value']}")

    rec = dash["receivables"]
    bucket_sum = round(sum(b["amount"] for b in rec["buckets"]), 2)
    check("ageing buckets sum to the total",
          abs(bucket_sum - rec["total"]) < 0.5, f"{bucket_sum} vs {rec['total']}")
    check("near-expiry stock is surfaced", dash["stock"]["near_expiry_value"] > 0,
          str(dash["stock"]["near_expiry_value"]))
    check("a SKU out of stock is never also in the movers list",
          not ({s["product_id"] for s in dash["stock"]["out_of_stock"]}
               & {s["product_id"] for s in dash["slow_movers"]}),
          "disjoint")

print()
print("=" * 72)
print("9. Two prints of one sale: the tax invoice and the shop's memo")
print("=" * 72)
# The firm has to raise a tax invoice on every sale, because the sale is its
# outward supply and goes into GSTR-1 whatever paper the shop gets. An
# unregistered kirana does not want that document on the counter, so the same
# invoice prints a second way: the shop's cash memo. The money has to be
# identical and the tax presentation has to be gone -- those are the two
# things worth asserting, and the second one only means something if the
# extraction below can actually see the tax invoice's own GSTIN.
#
# pypdf is a test-only dependency. reportlab compresses page streams, so
# searching the raw bytes for "GSTIN" finds nothing in either document and
# would pass vacuously.
from pypdf import PdfReader  # noqa: E402

_, company = call("GET", "/api/company")
_, recent = call("GET", "/api/invoices")
subject = recent[0] if isinstance(recent, list) else recent["items"][0]


def pdf_text(path: str) -> tuple[int, str]:
    """Fetch a PDF over HTTP and return its status and its visible text."""
    request = urllib.request.Request(f"{BASE}{path}", method="GET")
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        return error.code, ""
    if not raw.startswith(b"%PDF"):
        return 0, ""
    reader = PdfReader(io.BytesIO(raw))
    return 200, "\n".join(page.extract_text() or "" for page in reader.pages)


tax_status, tax_text = pdf_text(f"/api/invoices/{subject['id']}/pdf")
memo_status, memo_text = pdf_text(f"/api/invoices/{subject['id']}/pdf?format=memo")

check("the tax invoice prints", tax_status == 200, str(tax_status))
check("the shop's memo prints", memo_status == 200, str(memo_status))

# The control. If these fail the extraction is broken, and every absence
# asserted below is meaningless rather than true.
check("the tax invoice shows the firm's GSTIN",
      company["gstin"] in tax_text, company["gstin"])
check("the tax invoice shows HSN and the tax heads",
      "HSN" in tax_text and ("CGST" in tax_text or "IGST" in tax_text))

check("the memo is headed CASH MEMO, not TAX INVOICE",
      "CASH MEMO" in memo_text and "TAX INVOICE" not in memo_text)
check("the memo carries no GSTIN at all",
      "GSTIN" not in memo_text and company["gstin"] not in memo_text)
check("the memo carries no HSN code", "HSN" not in memo_text)
check("the memo shows no tax split",
      not any(head in memo_text for head in ("CGST", "SGST", "IGST")))
check("the memo omits the Rule 46 amount in words",
      "Amount in words" not in memo_text)
check("the memo says on its face that it is not a tax invoice",
      "not a tax invoice" in memo_text)

# Same sale, so the same reference and the same money.
check("the memo cites the bill number",
      subject["invoice_no"] in memo_text, subject["invoice_no"])
payable = f"{subject['grand_total']:,.2f}"
check("the memo's total is the invoice's payable amount",
      payable in memo_text, payable)
check("the shop's name is on the memo",
      subject["retailer_name"].split()[0] in memo_text)

# Printing is a read. Nothing about the sale may move because a different
# piece of paper came out of it.
_, after = call("GET", f"/api/invoices/{subject['id']}")
check("printing the memo changed nothing about the invoice",
      abs(after["grand_total"] - subject["grand_total"]) < 0.005
      and after["invoice_no"] == subject["invoice_no"])

status_bad, _ = call("GET", f"/api/invoices/{subject['id']}/pdf?format=receipt")
check("an unknown print format is refused", status_bad == 422, str(status_bad))

print()
print("=" * 72)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")
if failed:
    for name in failed:
        print(f"  FAILED: {name}")
print("=" * 72)
sys.exit(1 if failed else 0)
