"""End-to-end check of orders, load sheets and credit notes.

Run against a live server:  python smoke_test_field.py [base_url]

Walks the real chain — take an order, build a load sheet, pick it, deliver
it, then credit part of it back — and checks that stock and the receivable
move by exactly the right amounts at each step.

Call logging and the day plan used to be tested here. Both are gone from the
app, so the sections that covered them have been replaced by checks on what
replaced them: routes as standing lists, and orders that stand alone.
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


def stock_pieces():
    _, snapshot = call("GET", "/api/stock")
    return snapshot["totals"]["pieces"]


print("=" * 72)
print("1. Routes are standing lists, not trips")
print("=" * 72)
status, routes = call("GET", "/api/routes")
check("routes load", status == 200, str(status))
if status == 200:
    check("there are routes", len(routes) > 0, f"{len(routes)} routes")
    check("each route has a name and a weekday",
          all(r["name"] and 0 <= r["day_of_week"] <= 6 for r in routes))
    check("each route carries its shop count",
          all(isinstance(r["retailer_count"], int) for r in routes))
    check("routes no longer carry a salesman",
          all("salesman_name" not in r and "salesman_id" not in r for r in routes),
          "no salesman fields")
    check("every shop on a route is counted",
          sum(r["retailer_count"] for r in routes) > 0,
          f"{sum(r['retailer_count'] for r in routes)} shops on routes")

# The word "beat" changed meaning. It used to be a territory with a standing
# weekday, which is now a Route; a beat is one van's trip on one day. So
# /api/beats still answers -- it just answers about something else, and the
# old shape must not be there.
status, beats = call("GET", "/api/beats?limit=5")
check("/api/beats now returns van trips, not territories", status == 200,
      str(status))
if status == 200 and beats:
    check("a beat has a date and a stage, not a weekday",
          all("beat_date" in b and "status" in b and "weekday" not in b
              for b in beats),
          f"{len(beats)} beats")
    check("territories moved to /api/routes",
          all("retailer_count" not in b for b in beats),
          "no shop counts on a beat")

print()
print("=" * 72)
print("2. Call logging is gone, orders are not")
print("=" * 72)
for path in ("/api/field/day", "/api/field/no-order-reasons", "/api/visits",
             "/api/users", "/api/events"):
    status, _ = call("GET", path)
    check(f"{path} is gone", status == 404, str(status))

status, orders = call("GET", "/api/orders?limit=5")
check("orders still load", status == 200, str(status))
if status == 200 and orders:
    check("an order carries no salesman", "salesman" not in orders[0],
          "no salesman field")
    check("an order names its route", "route" in orders[0], "route field present")

print()
print("=" * 72)
print("3. Taking an order moves no stock")
print("=" * 72)
_, products = call("GET", "/api/products")
# Tomorrow, so nothing already seeded for today is disturbed.
today = dt.date.today().isoformat()
tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
_, shops = call("GET", "/api/retailers?limit=50")
active = [s for s in shops if s["is_active"] and s.get("route_id")]
check("there is an active shop on a route to order for", len(active) > 0,
      f"{len(active)} shops")

order_id = None
if active:
    shop = active[0]
    before_stock = stock_pieces()
    status, order = call("POST", "/api/orders", {
        "retailer_id": shop["id"],
        "order_date": tomorrow,
        "lines": [
            {"product_id": products[0]["id"], "cases": 2},
            {"product_id": products[1]["id"], "cases": 1},
        ],
    })
    check("order captured", status == 201, str(status) if status != 201 else order["order_no"])
    if status == 201:
        order_id = order["id"]
        check("order starts pending", order["status"] == "pending", order["status"])
        check("order has an indicative value", order["estimated_value"] > 0,
              str(order["estimated_value"]))
        check("stock untouched by an order", stock_pieces() == before_stock,
              f"{stock_pieces()} vs {before_stock}")
        _, detail = call("GET", f"/api/orders/{order['id']}")
        check("order shows per-line availability",
              len(detail["availability"]) == len(order["lines"]))

print()
print("=" * 72)
print("4. Beats replace load sheets")
print("=" * 72)
# Load sheets and the /api/dispatches routes were replaced by beats, which
# are one van's trip rather than a picking document. Assert the old paths are
# gone so nothing can quietly fall back to them.
for path in ("/api/dispatches", "/api/dispatches/pending-orders"):
    status, _ = call("GET", path)
    check(f"{path} is gone", status == 404, str(status))

_, pending = call("GET", "/api/beats/pending-orders")
check("pending orders listed", len(pending) > 0, f"{len(pending)} waiting")

beat_id = None
if pending:
    route_id = pending[0]["route_id"]
    same_route = [o for o in pending if o["route_id"] == route_id]
    # Dated today, because the van is going to be loaded and billed in this
    # same run. A beat planned for tomorrow can be built now but not loaded
    # until tomorrow -- loading posts stock movements, and billing writes a
    # tax invoice, on the beat's own date.
    # The orders are named explicitly rather than swept up by route. Left to
    # itself a beat takes only the orders wanted by its own date, and the
    # demo's pending orders were asked for tomorrow -- which is the right
    # default and the wrong thing for a test that then bills the van.
    status, beat = call("POST", "/api/beats", {
        "beat_date": today,
        "route_id": route_id,
        "order_ids": [o["id"] for o in same_route],
        "vehicle_no": "OD 09 SMOKE 1",
        "person_name": "Smoke",
    })
    check("beat planned", status == 201,
          str(status) if status != 201 else beat["beat_no"])
    if status == 201:
        beat_id = beat["id"]
        check("every pending order for the route is a stop",
              beat["stop_count"] == len(same_route),
              f"{beat['stop_count']} stops vs {len(same_route)} orders")
        check("stops are sequenced",
              [s["sequence"] for s in beat["stops"]]
              == list(range(1, beat["stop_count"] + 1)))
        check("planning moves no stock", beat["is_empty"],
              f"{beat['on_van_pieces']} pieces")

        # The restraint itself: a beat dated today does not help itself to
        # orders that were asked for tomorrow.
        status, body = call("POST", "/api/beats", {
            "beat_date": today,
            "route_id": route_id,
        })
        check("a beat does not sweep up orders wanted on a later day",
              status == 422 and "at least one stop" in str(body),
              str(body)[:80])

        _, picks = call("GET", f"/api/beats/{beat_id}/pick-list")
        order_lines = sum(len(o["lines"]) for o in same_route)
        check("pick list consolidates by product",
              len(picks["lines"]) <= order_lines,
              f"{len(picks['lines'])} picks for {order_lines} order lines")
        check("pick list totals cases", picks["total_cases"] > 0,
              f"{picks['total_cases']} cases")
        check("picks name a batch",
              all(line["batches"] or line["short_by"] > 0
                  for line in picks["lines"]))

        # Those orders should no longer be offered for another beat.
        _, still = call("GET", "/api/beats/pending-orders")
        check("orders on a beat leave the pending list",
              all(o["route_id"] != route_id for o in still),
              f"{len(still)} still pending")

    # A beat for tomorrow can be planned now, but nothing may happen on it
    # until its own date.
    status, future = call("POST", "/api/beats", {
        "beat_date": tomorrow,
        "retailer_ids": [pending[0]["retailer_id"]],
        "vehicle_no": "OD 09 SMOKE 2",
    })
    check("a beat can be planned for a future date", status == 201, str(status))
    if status == 201:
        status, body = call("POST", f"/api/beats/{future['id']}/load", {
            "extra": [{"product_id": pending[0]["lines"][0]["product_id"],
                       "cases": 1}],
        })
        check("but it cannot be loaded before that date", status == 422,
              str(body)[:90])
        check("and it stays planned",
              call("GET", f"/api/beats/{future['id']}")[1]["status"] == "planned",
              "planned")

print()
print("=" * 72)
print("5. Loading, then billing a stop from the van")
print("=" * 72)
if beat_id:
    before_stock = stock_pieces()
    _, picks = call("GET", f"/api/beats/{beat_id}/pick-list")
    expected_short = {line["product_id"] for line in picks["short_lines"]}
    status, beat = call("POST", f"/api/beats/{beat_id}/load", {})
    check("van loaded", status == 200, str(status))
    if status == 200:
        # One SKU being out of stock must not keep the van off the road: the
        # other shops on the route still want serving, and the one that
        # ordered the missing line gets short-delivered.
        reported = {line["product_id"] for line in beat["could_not_load"]}
        check("what the godown could not supply is reported, not refused",
              reported == expected_short,
              f"{len(reported)} short lines, pick list warned of "
              f"{len(expected_short)}")
        check("a short line says how much is missing",
              all(line["short_pieces"] > 0
                  and line["loaded_pieces"] < line["asked_pieces"]
                  for line in beat["could_not_load"]),
              f"{len(reported)} lines")
        if reported:
            check("the beat's note records that it went out short",
                  "short" in (beat["note"] or "").lower(),
                  beat["note"] or "")
        check("loading moves stock without changing the total",
              stock_pieces() == before_stock,
              f"{stock_pieces()} vs {before_stock}")
        check("the van is now carrying goods", beat["on_van_pieces"] > 0,
              f"{beat['on_van_pieces']} pieces")

        stop = beat["stops"][0]
        before_stock = stock_pieces()
        status, result = call(
            "POST", f"/api/beats/{beat_id}/stops/{stop['id']}/bill",
            {},
        )
        check("stop billed", status == 201,
              str(status) if status != 201 else result["invoice_no"])
        if status == 201:
            after_stock = stock_pieces()
            check("stock fell when the goods were handed over",
                  after_stock < before_stock,
                  f"{before_stock} -> {after_stock}")
            _, invoice = call("GET", f"/api/invoices/{result['invoice_id']}")
            check("the bill says which beat and order it came from",
                  "Billed on" in (invoice["note"] or "")
                  and "against" in (invoice["note"] or ""),
                  invoice["note"] or "")
            _, again = call("GET", f"/api/beats/{beat_id}")
            row = next(s for s in again["stops"] if s["id"] == stop["id"])
            check("the stop is marked billed", row["billed"] is True)
            check("the beat tracks progress", again["billed_count"] == 1,
                  str(again["billed_count"]))
            check("billing moved the beat to out", again["status"] == "out",
                  again["status"])

            status, _ = call(
                "POST", f"/api/beats/{beat_id}/stops/{stop['id']}/bill",
                {},
            )
            check("cannot bill the same stop twice", status == 422, str(status))

            globals()["delivered_invoice"] = result["invoice_id"]

print()
print("=" * 72)
print("6. Credit notes reverse tax, stock and the receivable")
print("=" * 72)
invoice_id = globals().get("delivered_invoice")
if invoice_id:
    _, before = call("GET", f"/api/invoices/{invoice_id}")
    _, open_lines = call("GET", f"/api/invoices/{invoice_id}/returnable")
    check("returnable lines listed", len(open_lines["lines"]) > 0)

    line = next(
        (l for l in open_lines["lines"]
         if not l["is_free"] and l["returnable_pieces"] >= l["pieces_per_case"]),
        None,
    )
    if line:
        before_stock = stock_pieces()
        # The invoice being credited was billed off a van. The goods must come
        # back to the godown, not to a beat that may already have closed, so
        # the godown figure is what has to rise.
        _, stock_before = call("GET", "/api/stock")
        godown_before = stock_before["totals"]["godown_pieces"]
        status, note = call("POST", "/api/credit-notes", {
            "invoice_id": invoice_id,
            "reason": "return_saleable",
            "lines": [{"invoice_line_id": line["invoice_line_id"], "cases": 1}],
        })
        check("saleable credit note raised", status == 201,
              str(note)[:140] if status != 201 else note["note_no"])
        if status == 201:
            check("note number fits the 16-char GST limit",
                  len(note["note_no"]) <= 16, note["note_no"])
            check("tax reversed at the invoice's own rate",
                  abs(note["lines"][0]["gst_rate"] - line["gst_rate"]) < 0.001,
                  f"{note['lines'][0]['gst_rate']} vs {line['gst_rate']}")
            check("credit total is a whole rupee",
                  abs(note["grand_total"] - round(note["grand_total"])) < 0.001,
                  str(note["grand_total"]))
            check("saleable return goes back into stock",
                  stock_pieces() == before_stock + line["pieces_per_case"],
                  f"{before_stock} -> {stock_pieces()}")
            _, stock_after = call("GET", "/api/stock")
            godown_after = stock_after["totals"]["godown_pieces"]
            check("a van sale is credited back to the godown, not to the van",
                  godown_after == godown_before + line["pieces_per_case"],
                  f"{godown_before} -> {godown_after}")

            _, after = call("GET", f"/api/invoices/{invoice_id}")
            check("invoice balance falls by the credit",
                  abs((before["balance"] - note["grand_total"]) - after["balance"]) < 0.01,
                  f"{before['balance']} - {note['grand_total']} vs {after['balance']}")
            check("invoice reports what was credited",
                  abs(after["credited"] - note["grand_total"]) < 0.01,
                  str(after["credited"]))

            _, reopened = call("GET", f"/api/invoices/{invoice_id}/returnable")
            same = next(
                l for l in reopened["lines"]
                if l["invoice_line_id"] == line["invoice_line_id"]
            )
            check("returnable quantity shrinks",
                  same["returnable_pieces"]
                  == line["returnable_pieces"] - line["pieces_per_case"],
                  f"{line['returnable_pieces']} -> {same['returnable_pieces']}")

            over = same["returnable_pieces"] // same["pieces_per_case"] + 5
            status, body = call("POST", "/api/credit-notes", {
                "invoice_id": invoice_id,
                "reason": "return_saleable",
                "lines": [
                    {"invoice_line_id": line["invoice_line_id"], "cases": over}
                ],
            })
            check("cannot credit more than was sold", status == 422, str(status))

print()
print("=" * 72)
print("7. Damaged returns never re-enter saleable stock")
print("=" * 72)
if invoice_id:
    _, open_lines = call("GET", f"/api/invoices/{invoice_id}/returnable")
    line = next(
        (l for l in open_lines["lines"]
         if not l["is_free"] and l["returnable_pieces"] >= l["pieces_per_case"]),
        None,
    )
    if line:
        before_stock = stock_pieces()
        _, before_damage = call("GET", "/api/damage-register")
        status, note = call("POST", "/api/credit-notes", {
            "invoice_id": invoice_id,
            "reason": "return_damaged",
            "lines": [{"invoice_line_id": line["invoice_line_id"], "cases": 1}],
        })
        check("damaged credit note raised", status == 201,
              str(note)[:140] if status != 201 else note["note_no"])
        if status == 201:
            check("saleable stock is unchanged", stock_pieces() == before_stock,
                  f"{before_stock} -> {stock_pieces()}")
            _, after_damage = call("GET", "/api/damage-register")
            check("damage register grew",
                  after_damage["total_pieces"]
                  == before_damage["total_pieces"] + line["pieces_per_case"],
                  f"{before_damage['total_pieces']} -> {after_damage['total_pieces']}")
            check("damage is valued at cost", after_damage["total_value"] > 0,
                  str(after_damage["total_value"]))
            check("the retailer is still credited", note["grand_total"] > 0,
                  str(note["grand_total"]))

print()
print("=" * 72)
print("8. The dashboard reflects all of it")
print("=" * 72)
status, dash = call("GET", "/api/dashboard")
check("dashboard loads", status == 200, str(status))
if status == 200:
    check("no targets anywhere",
          "target" not in json.dumps(dash), "no target key")
    check("no salesmen table", "salesmen" not in dash, "no salesmen key")
    check("no call statistics", "field" not in dash, "no field key")
    check("month reports value and cases",
          dash["month"]["value"] >= 0 and dash["month"]["cases"] >= 0,
          f"{dash['month']['value']} / {dash['month']['cases']} cases")
    check("quarter is at least the month",
          dash["quarter"]["value"] >= dash["month"]["value"],
          f"Q {dash['quarter']['value']} vs M {dash['month']['value']}")
    check("returns reported", dash["returns"]["credit_notes"] > 0,
          str(dash["returns"]["credit_notes"]))

    rec = dash["receivables"]
    bucket_sum = round(sum(b["amount"] for b in rec["buckets"]), 2)
    check("ageing still ties after credit notes",
          abs(bucket_sum - rec["total"]) < 0.5, f"{bucket_sum} vs {rec['total']}")

    overdue = round(
        sum(b["amount"] for b in rec["buckets"] if b["label"] != "current"), 2
    )
    check("overdue is everything not current",
          abs(rec["overdue"] - overdue) < 0.5,
          f"{rec['overdue']} vs {overdue}")
    check("overdue never exceeds the total", rec["overdue"] <= rec["total"] + 0.5,
          f"{rec['overdue']} of {rec['total']}")

print()
print("=" * 72)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")
for name in failed:
    print(f"  FAILED: {name}")
print("=" * 72)
sys.exit(1 if failed else 0)
