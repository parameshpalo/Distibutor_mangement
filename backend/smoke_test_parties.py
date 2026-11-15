"""End-to-end check of party types, inclusive pricing and master editing.

Run against a live server:  python smoke_test_parties.py [base_url]

Three things are being proved here.

A buyer without a GSTIN can be created on the spot and billed. That bill
is an ordinary tax invoice: it carries GST, it reaches GSTR-1, and it
lands in B2CS because the buyer is unregistered. Nothing is off the books.

An inclusive bill lands exactly on the money the buyer agreed. The tax is
contained in the quoted rate rather than added to it, and the taxable
value is the balancing figure, so the printed total is the figure that was
shaken on.

A sub-distributor is billed at PTD, not PTR, and a product can be edited
or retired without disturbing any invoice already raised.
"""

import datetime as dt
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8095"
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


TODAY = dt.date.today().isoformat()
stamp = dt.datetime.now().strftime("%H%M%S")

status, products = call("GET", "/api/products")
assert status == 200 and products, "no products; seed the database first"
# Something with stock, so the bills below are not blocked by the godown.
status, stock_rows = call("GET", "/api/stock")
on_hand = {}
if status == 200:
    rows = stock_rows if isinstance(stock_rows, list) else stock_rows.get("products", [])
    for row in rows:
        on_hand[row.get("product_id")] = row.get("sellable_pieces", 0) or 0
stocked = [p for p in products if on_hand.get(p["id"], 0) > 2000] or products
product = stocked[0]


print("=" * 72)
print("1. A shop with no GSTIN can be added on the spot")
print("=" * 72)
status, walkin = call("POST", "/api/retailers", {
    "shop_name": f"Walk-in Kirana {stamp}",
    "owner_name": "Cash buyer",
    "party_type": "retailer",
    "price_mode": "inclusive",
    "outlet_type": "kirana",
    "credit_limit": 0,
    "credit_days": 0,
})
check("party created without a GSTIN", status == 201, str(status))
if status == 201:
    check("stored as unregistered", walkin["is_registered"] is False)
    check("gstin is null, not an empty string", walkin["gstin"] is None,
          repr(walkin["gstin"]))
    check("party type recorded", walkin["party_type"] == "retailer",
          walkin["party_type"])
    check("price mode recorded", walkin["price_mode"] == "inclusive",
          walkin["price_mode"])
    check("given a code automatically", bool(walkin["code"]), walkin["code"])

status, bad = call("POST", "/api/retailers", {
    "shop_name": f"Mismatch Traders {stamp}",
    "gstin": "29AAACR9999Q1ZX",  # 29 is Karnataka
    "state_code": "36",          # but the state says Telangana
})
check("a GSTIN that disagrees with the state is refused", bad is not None
      and status == 422, str(status))


print()
print("=" * 72)
print("2. An inclusive bill lands on the agreed figure")
print("=" * 72)
status, preview = call("POST", "/api/invoices/preview", {
    "retailer_id": walkin["id"],
    "invoice_date": TODAY,
    "lines": [{"product_id": product["id"], "cases": 2, "discount_pct": 0}],
})
check("priced inclusive", status == 200 and preview["price_mode"] == "inclusive",
      preview.get("price_mode") if status == 200 else str(status))
if status == 200:
    line = preview["lines"][0]
    quoted = line["quoted_rate_per_piece"]
    check("the agreed all-in rate is reported back", quoted is not None,
          str(quoted))
    expected = round(quoted * line["qty_pieces"], 2)
    check("line total equals rate x quantity, to the paise",
          abs(line["line_total"] - expected) < 0.005,
          f"{line['line_total']:,.2f} vs {expected:,.2f}")
    check("tax is contained in it, not added to it",
          line["taxable"] < line["line_total"],
          f"taxable {line['taxable']:,.2f} < total {line['line_total']:,.2f}")
    check("the tax is still charged, not waived", line["tax"] > 0,
          f"{line['tax']:,.2f}")
    totals = preview["totals"]
    check("CGST and SGST are equal, as the law requires",
          abs(totals["cgst_total"] - totals["sgst_total"]) < 0.005,
          f"{totals['cgst_total']:,.2f} / {totals['sgst_total']:,.2f}")

status, exclusive = call("POST", "/api/invoices/preview", {
    "retailer_id": walkin["id"],
    "invoice_date": TODAY,
    "price_mode": "exclusive",
    "lines": [{"product_id": product["id"], "cases": 2, "discount_pct": 0}],
})
check("the mode can be overridden for one bill",
      status == 200 and exclusive["price_mode"] == "exclusive",
      exclusive.get("price_mode") if status == 200 else str(status))
if status == 200:
    check("the same goods cost the same either way",
          abs(exclusive["totals"]["grand_total"]
              - preview["totals"]["grand_total"]) <= 1.0,
          f"{exclusive['totals']['grand_total']:,.2f} vs "
          f"{preview['totals']['grand_total']:,.2f}")
    check("but the taxable value is identical",
          abs(exclusive["totals"]["taxable_total"]
              - preview["totals"]["taxable_total"]) <= 1.0,
          f"{exclusive['totals']['taxable_total']:,.2f} vs "
          f"{preview['totals']['taxable_total']:,.2f}")


print()
print("=" * 72)
print("3. The bill is raised, and it is a real tax invoice")
print("=" * 72)
status, invoice = call("POST", "/api/invoices", {
    "retailer_id": walkin["id"],
    "invoice_date": TODAY,
    "lines": [{"product_id": product["id"], "cases": 2, "discount_pct": 0}],
})
check("invoice raised for an unregistered buyer", status == 201, str(status))
if status == 201:
    check("mode stored on the invoice", invoice["price_mode"] == "inclusive",
          invoice["price_mode"])
    check("no buyer GSTIN on it", invoice["retailer_gstin"] is None)
    check("GST was charged",
          invoice["cgst_total"] + invoice["sgst_total"] + invoice["igst_total"] > 0,
          f"{invoice['cgst_total'] + invoice['sgst_total']:,.2f}")
    check("the quoted rate is kept on the line",
          invoice["lines"][0]["quoted_rate_per_piece"] is not None)
    check("taxable + tax + round-off = payable",
          abs(invoice["taxable_total"] + invoice["cgst_total"]
              + invoice["sgst_total"] + invoice["igst_total"]
              + invoice["round_off"] - invoice["grand_total"]) < 0.005,
          f"{invoice['grand_total']:,.2f}")

    status, pdf = call("GET", f"/api/invoices/{invoice['id']}/pdf")
    check("it prints", status == 200, str(status))

    today = dt.date.fromisoformat(TODAY)
    status, gstr1 = call(
        "GET", f"/api/gst/gstr1?year={today.year}&month={today.month}"
    )
    if status == 200:
        by_code = {s["code"]: s for s in gstr1["sections"]}
        check("the sale reached GSTR-1, in B2CS",
              by_code["B2CS"]["taxable"] >= invoice["taxable_total"] - 0.01,
              f"B2CS {by_code['B2CS']['taxable']:,.2f} >= "
              f"{invoice['taxable_total']:,.2f}")
        sections_net = sum(
            by_code[c]["taxable"] for c in ("B2B", "B2CL", "B2CS", "CDNR")
        )
        check("the return still reconciles to the books",
              abs(sections_net - gstr1["totals"]["taxable"]) < 1.0,
              f"{sections_net:,.2f} vs {gstr1['totals']['taxable']:,.2f}")


print()
print("=" * 72)
print("4. A sub-distributor is billed at PTD, not PTR")
print("=" * 72)
status, sub = call("POST", "/api/retailers", {
    "shop_name": f"Sub-distributor {stamp}",
    "party_type": "distributor",
    "gstin": "36AAACR7777Q1Z5",
    "state_code": "36",
    "outlet_type": "wholesale",
    "credit_limit": 500000,
    "credit_days": 21,
})
check("sub-distributor created", status == 201, str(status))
if status == 201:
    status, sub_preview = call("POST", "/api/invoices/preview", {
        "retailer_id": sub["id"],
        "invoice_date": TODAY,
        "lines": [{"product_id": product["id"], "cases": 1, "discount_pct": 0}],
    })
    status2, shop_preview = call("POST", "/api/invoices/preview", {
        "retailer_id": walkin["id"],
        "invoice_date": TODAY,
        "price_mode": "exclusive",
        "lines": [{"product_id": product["id"], "cases": 1, "discount_pct": 0}],
    })
    if status == 200 and status2 == 200:
        check("party type reported", sub_preview["party_type"] == "distributor",
              sub_preview["party_type"])
        sub_rate = sub_preview["lines"][0]["rate_per_piece"]
        shop_rate = shop_preview["lines"][0]["rate_per_piece"]
        check("the sub-distributor's rate is the lower one",
              sub_rate < shop_rate, f"PTD {sub_rate} < PTR {shop_rate}")
        check("it matches the product master's PTD",
              abs(sub_rate - product["ptd"]) < 0.01,
              f"{sub_rate} vs {product['ptd']}")


print()
print("=" * 72)
print("5. A line rate can be overridden, because the trade haggles")
print("=" * 72)
status, haggled = call("POST", "/api/invoices/preview", {
    "retailer_id": walkin["id"],
    "invoice_date": TODAY,
    "price_mode": "exclusive",
    "lines": [{
        "product_id": product["id"], "cases": 1,
        "rate_per_piece": 3.5, "discount_pct": 0,
    }],
})
check("an agreed rate overrides the master", status == 200
      and abs(haggled["lines"][0]["rate_per_piece"] - 3.5) < 0.01,
      str(haggled["lines"][0]["rate_per_piece"]) if status == 200 else str(status))


print()
print("=" * 72)
print("6. Products can be added, edited and retired")
print("=" * 72)
sku = f"TEST-{stamp}"
status, fresh = call("POST", "/api/products", {
    "sku_code": sku,
    "brand": "Test Brand",
    "name": "Smoke Biscuit",
    "pack_size_g": 100,
    "pieces_per_case": 60,
    "hsn": "1905",
    "mrp": 20,
    "ptr": 15,
    "ptd": 14,
    "default_discount_pct": 2.5,
})
check("product created", status == 201, str(status))
if status == 201:
    check("default discount stored",
          abs(fresh["default_discount_pct"] - 2.5) < 0.001,
          str(fresh["default_discount_pct"]))

    status, edited = call("PATCH", f"/api/products/{fresh['id']}", {
        "mrp": 25, "default_discount_pct": 5,
    })
    check("product edited", status == 200, str(status))
    if status == 200:
        check("MRP changed", abs(edited["mrp"] - 25) < 0.01, str(edited["mrp"]))
        check("discount changed",
              abs(edited["default_discount_pct"] - 5) < 0.001,
              str(edited["default_discount_pct"]))
        check("untouched fields kept their values",
              abs(edited["ptr"] - 15) < 0.01, str(edited["ptr"]))

    status, bad_hsn = call("PATCH", f"/api/products/{fresh['id']}",
                           {"hsn": "9999"})
    check("an HSN with no GST rate is refused", status in (422, 400),
          str(status))

    status, gone = call("DELETE", f"/api/products/{fresh['id']}")
    check("a product with no history is deleted outright",
          status == 200 and gone["deleted"] is True,
          json.dumps(gone) if status == 200 else str(status))

# A product that has been sold must survive deletion as a retirement.
status, used = call("DELETE", f"/api/products/{product['id']}")
check("a product with history is retired, not deleted",
      status == 200 and used["deleted"] is False and used["deactivated"] is True,
      used.get("message", "")[:70] if status == 200 else str(status))
if status == 200:
    status, back = call("PATCH", f"/api/products/{product['id']}",
                        {"is_active": True})
    check("and can be brought back", status == 200 and back["is_active"] is True,
          str(status))


print()
print("=" * 72)
print("7. Parties can be edited without collateral damage")
print("=" * 72)
status, patched = call("PATCH", f"/api/retailers/{walkin['id']}", {
    "phone": "9876500000",
})
check("party edited", status == 200, str(status))
if status == 200:
    check("the field sent was written", patched["phone"] == "9876500000",
          patched["phone"])
    check("credit limit was not reset by the partial update",
          patched["credit_limit"] == walkin["credit_limit"],
          f"{patched['credit_limit']} vs {walkin['credit_limit']}")
    check("price mode was not reset either",
          patched["price_mode"] == "inclusive", patched["price_mode"])

status, registered = call("PATCH", f"/api/retailers/{walkin['id']}", {
    "gstin": "36AAACR8888Q1Z3", "price_mode": "exclusive",
})
check("a shop that registers later can be updated", status == 200, str(status))
if status == 200:
    check("it is now marked registered",
          registered["is_registered"] is True)
    check("and quoted exclusive from here on",
          registered["price_mode"] == "exclusive")

status, filtered = call("GET", "/api/retailers?party_type=distributor")
check("parties can be listed by type",
      status == 200 and all(p["party_type"] == "distributor" for p in filtered),
      f"{len(filtered)} distributors" if status == 200 else str(status))


print()
print("=" * 72)
print("8. Nothing earlier broke")
print("=" * 72)
status, dash = call("GET", "/api/dashboard")
check("dashboard still loads", status == 200, str(status))
status, stock_check = call("GET", "/api/stock")
check("stock still loads", status == 200, str(status))
status, invoices = call("GET", "/api/invoices?limit=5")
check("invoice list still loads", status == 200, str(status))

print()
print("=" * 72)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")
if failed:
    for name in failed:
        print(f"  FAILED: {name}")
print("=" * 72)
sys.exit(1 if failed else 0)
