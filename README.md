# Biscuit distribution

Stock, GST billing, van deliveries, collections and the GSTR-1 return for a
single-owner biscuit distributorship. One web app, no login, one SQLite file.

The business is a loop — goods come in, go out on a van, money comes back —
and the app is shaped like that loop:

| Screen | What it is for |
| --- | --- |
| **Today** | What needs doing now. Sales this month and quarter, what to bill, what to collect, what needs attention. |
| **Bill** | Raise a bill, at the counter or for a shop that walked in. |
| **Deliveries** | Van runs: the bills a van is carrying, and the list of goods to load. |
| **Money** | Who owes, oldest first, and recording what comes in. |
| **Stock** | On hand, near expiry, and goods received. |
| **Records** | Bills raised, returns, and the GST return. |
| **Setup** | Customers, products and rates, and the firm's own details. |

## The bill, and the van

**A bill is the only real object.** Raising one issues the invoice number,
takes the stock out of the godown and creates the receivable. That happens
whether the buyer carries the goods away himself or the owner drives them
over, because it is the same sale either way.

So every bill says how it leaves:

| | What it means |
| --- | --- |
| **Buyer collects** | `invoice.delivery_id` is null. Nothing else to arrange. |
| **I deliver it** | The bill is on a **van run**, and travels with the others on it. |

A van run is deliberately thin. It owns nothing and holds no quantities: it
is a number, a date, and bills pointing at it. There is no vehicle number
and no driver name: a firm this size has one or two vans and the owner
knows which went where, so those were two fields of typing that bought
nothing. What to
load is the sum of those bills' lines, worked out on read:

```
open  →  out  →  done
```

`open` while bills are still being added, `out` once the van has left, `done`
when it is back. There is no "loaded" stage, because the goods *are* the
bills — the run is loaded the moment the bills are on it.

That buys a flow that matches the order the work actually happens in. The
owner bills the shops he is delivering to, and the loading list builds
itself. He does not have to plan a trip before he can bill anyone.

**What it costs, stated plainly.** The van is not a stock location, so there
is no van balance to reconcile at the end of the day. If goods walk off a
van, the app will not tell you that evening — the next stock count will show
a difference nobody can attribute. An earlier version of this app tracked the
van as a stock location and reconciled every trip to zero; it was removed
because it forced a planning step before billing, and for a firm where the
owner drives the van himself, the reconciliation was not worth that.

Two smaller consequences:

- **Attaching a bill to a run moves no stock.** The stock left when the bill
  was raised. Putting a bill on a van, or taking it off, is a filing
  decision, so it is safe to undo and the bill is untouched by it.
- **Loose stock on the van is not tracked.** A van often carries goods nobody
  has ordered. Those are still godown stock until someone bills them; the
  ad-hoc bill is raised at the shop and added to the same run.

### Where the van run is on screen

The same panel (`frontend/src/components/VanRun.jsx`) is rendered in two
places, so they cannot drift apart:

- **Deliveries** — pick a run from the list and the panel opens under it.
- **Bill** — choose *I deliver it* and the panel appears below the form for
  the run you selected.

That second one is the point. After a bill is raised onto a van the screen
stays on Bill: the shop field clears, the van stays selected, and the panel
underneath refreshes with the new bill, the new loading list and the **Send
the van out** button. Billing the next shop on the same run is one form away
rather than two navigations, and the van can be sent out without leaving the
billing screen.

## The catalogue

`backend/app/catalogue.py` holds the 105 SKUs the company sells, read out of
its monthly order sheet for this cluster (`Western Odisha_Order Sheet
Nov'26-V1.xlsx`, sheet `Order Sheet`, stamped Version Oct2026-V1).

Taken straight from the sheet, per SKU: brand group, product name, pack size,
packets per case, MRP, the company's basic rate per case, and the purchase
scheme %. On all 105 lines that basic rate is 75.687% of the case's MRP value
— one landing rate for the whole range, not per-SKU pricing.

Four things the sheet does **not** state, so the app supplies them and they
should be checked before anyone bills a real customer:

| Field | How it is derived | Why it is a guess |
| --- | --- | --- |
| `ptr` | MRP, less GST, less a 12% retailer margin | The sheet is a buying document; it never says what a shop pays |
| `ptd` | landing rate + 4% | Nor what a sub-distributor pays |
| `shelf_life_days` | banded: cakes 90, creams 180, rest 270 | The sheet carries no dating |
| `sku_code` | generated from brand, name and grams | The company's sheet has no codes at all |

`default_discount_pct` is deliberately **0** on every SKU. The sheet's scheme
% is what the company allows *him*; it is not a discount he gives a shop. How
much of it he passes on is his decision, set per SKU under Setup.

## Running it

Two processes. The API first:

```bash
cd backend && python -m app.init --gstin <his GSTIN> --name "<firm name>"
```

```bash
cd backend && python -m uvicorn app.main:app --port 8095
```

Then the web app, which proxies `/api` to the port above:

```bash
cd frontend && npm install && npm run dev
```

Open the URL Vite prints — on Windows use `localhost`, not `127.0.0.1`, since
Vite binds IPv6. Interactive API docs are at `/docs` on the API port.

`app.init` creates the schema, one company profile, the GST rates for HSN
1905 and the catalogue. **It writes no transactions and invents nothing**:
anything not given on the command line is left blank and listed on Setup → My
firm as still needed. The first real entry is a goods-received note, because
nothing can be sold before something has arrived.

To look around with data in it instead:

```bash
cd backend && python -m app.rebuild --demo --force
```

On Windows, a restart is easier through the script, which kills whatever holds
the port by pid and waits for the server to answer:

```bash
cd backend && powershell -ExecutionPolicy Bypass -File restart_api.ps1 -Port 8095
```

### Changing the schema

There are no migrations. `app/rebuild.py` drops what is actually in the file —
reflected, not taken from the models, so tables left behind by an older
version go too — and recreates it. Adding a stock reason changes a SQL `CHECK`
constraint, which SQLite cannot alter in place, so an existing database would
reject the new reason with an opaque `IntegrityError`.

**This is fine before go-live and impossible after.** Alembic has to go in
before he bills a real customer.

## Checking it

Six suites. Five drive the HTTP API; the sixth runs `app.init` offline against
throwaway databases. Each HTTP suite spends some of the demo's state — orders,
stock, credit — so reseed between them:

```bash
cd backend && python smoke_test_init.py
```

```bash
cd backend && python -m app.rebuild --demo --force && python smoke_test.py
```

```bash
cd backend && python -m app.rebuild --demo --force && python smoke_test_parties.py
```

```bash
cd backend && python -m app.rebuild --demo --force && python smoke_test_field.py
```

```bash
cd backend && python -m app.rebuild --demo --force && python smoke_test_gst.py
```

| Suite | What it covers | Assertions |
| --- | --- | --- |
| `smoke_test_init.py` | Starting a real database: the catalogue loads, the state comes off the GSTIN, blanks stay blank, and a populated database is not destroyed by accident | 43 |
| `smoke_test.py` | Goods inward, pricing, invoicing, the stock stop, the credit *warning*, payment allocation, dashboard totals, and the two prints of one sale | 63 |
| `smoke_test_parties.py` | The two kinds of buyer, all-in pricing, master editing | 51 |
| `smoke_test_field.py` | Orders, routes, billing, then crediting part of a bill back to the godown | not yet rewritten for van runs |
| `smoke_test_gst.py` | GSTR-1 reconciles to the books; each section carries only what belongs in it; e-invoicing and e-way bills are absent | 35 |

**The suites have not caught up with van runs yet.** `smoke_test_beats.py`
tested the beat lifecycle and was deleted with it; `smoke_test_field.py` still
asserts the old flow and will fail until it is rewritten. The counts above are
from the last run before that change, except where marked. The van run flow
has been exercised end to end by hand — bills onto a run, the loading list,
out, back, and both refusals — but that is not the same as a suite, and this
line stays here until it is.

## Two kinds of buyer

Not every customer is a kirana. Some are sub-distributors who buy by the
pallet and resell onward, so `party_type` decides the price: a retailer is
billed at PTR, a sub-distributor at the lower PTD.

**A GSTIN is optional.** Most small shops are below the registration
threshold. The party form leaves it blank, the bill prints "GSTIN:
Unregistered", and the sale is reported in GSTR-1 under B2CS rather than B2B.
A shop that registers later can be edited in place and its later bills move to
B2B on their own.

**"No GST" means an all-in rate, not an untaxed sale.** When a shop says it
does not want GST, what it means is that it will pay one figure per case and
not a rate plus tax on top. That is a quoting convention, and `price_mode`
carries it: with `inclusive`, the agreed rate already contains the tax and the
tax is backed out of it. The supply is taxed at the same slab, the taxable
value and tax are recorded separately, and the invoice reaches GSTR-1 exactly
as any other does. The mode is stored on the invoice, not read from the party,
so a reprint shows what was agreed. There is no way to raise a bill that stays
off the books, and there should not be.

The arithmetic is done tax-first: CGST and SGST are rounded from the same
half-rate so they stay equal, and the taxable value is the balancing figure.
Rounding the taxable value first and then the tax leaves the line a paise off
the figure the buyer agreed, which defeats the point.

**One sale, two prints.** A shop that does not want a GST bill on the counter
still has to be billed, because the sale is the firm's outward supply and
reaches GSTR-1 whatever paper changes hands. So the same invoice prints two
ways, from `GET /api/invoices/{id}/pdf`:

| `format` | Who keeps it | What is on it |
| --- | --- | --- |
| `invoice` (default) | the firm | the Rule 46 tax invoice: both GSTINs, HSN, taxable value, the tax split, place of supply, the amount in words |
| `memo` | the shop | particulars, quantity, an all-in rate and the amount; the FSSAI licence; "This is not a tax invoice" in the footer |

The memo's money is the invoice's money: same line amounts, same round-off,
same total. What is removed is the tax presentation, and removed deliberately
rather than hidden with CSS, because a page carrying the supplier's GSTIN
under a "TAX INVOICE" heading *is* a tax invoice, and handing out two of them
for one sale is how a duplicate-invoice problem starts. The memo's rate is
derived from the line amount rather than copied from the quoted rate: on an
exclusive-priced bill the quoted rate is before tax, and printing it on a slip
that shows no tax would understate the line by the whole of the GST. It
follows that rate times quantity can land a few paise from the amount, and the
amount is the figure that counts.

Printing either one is a read. Nothing in the database depends on which came
out of the printer.

## Decisions worth knowing

**Stock is never a stored number.** Every movement is an append-only row in
`stock_ledger` with a signed quantity and a reason. On-hand is always a SUM,
so any figure can be traced to the movements that produced it. A correction is
another row, never an edit, and `StockBatch` has no quantity column at all.

**Location is on the ledger, not on the batch.** One manufacturing lot sits in
the godown and on two vans at once. Splitting batches per location would
collide with the unique batch number and break the invoice-to-batch trail that
credit notes read to put stock back.

**Allocation is FEFO, not FIFO.** With a 6-to-9 month shelf life the oldest
*expiry* must leave first. Expired batches are excluded from sale outright, and
so are batches received after the invoice date, so back-dating a bill cannot
consume stock that had not yet arrived. The same test runs again at the van, so
a batch that expires between loading and delivery cannot be handed over.

**Money is exact.** Rupee amounts are stored as integer paise and per-piece
rates as integer ten-thousandths, so `SUM()` is exact and nothing drifts. All
arithmetic is Decimal; the API hands the browser numbers to format and no rupee
arithmetic happens in JavaScript.

**GST rates are dated, not stored on the product.** Rates are resolved against
the document date, so reprinting an old invoice reproduces the rate that applied
then. Biscuits (HSN 1905) changed slabs in the Sept-2025 rationalisation, which
is exactly the case this survives. **Confirm the current slab with his CA before
go-live** — the app ships 5%.

**Payments attach to invoices, not to retailers.** A receipt creates allocation
rows against specific invoices, oldest first, which is the only way ageing and
credit checks stay truthful once part-payments start — and with 7-21 day credit
they start immediately.

**The credit limit warns; it does not stop the bill.** It used to raise a 409
the biller had to override. The bill at a shop counter is written with the goods
already off the van, and a refusal at that moment helps nobody: the owner knows
which of his shops he will carry and the app does not. So the figure appears on
the billing preview and on Money, before the decision, and the bill always goes
through. A pleasant side effect is that `create_invoice` no longer has to price
the bill twice.

**An order is a promise; an invoice is a document of record.** Orders move no
stock and reserve nothing, so two orders can both promise the same cases and
loading the van resolves it. Stock moves and GST applies when the goods change
hands, which is also when the law says a supply happened.

**A credit note inherits the invoice's tax.** Rates are reversed at the slab
the original supply used, not today's, and the note keeps that supply's
intrastate or interstate character. Saleable returns go back to the batch they
left on, so they re-enter with their real expiry — and to the **godown**, not
to a van that may already have closed. Damaged stock is recorded coming back
and written off in the same breath: it nets to nothing on hand, and leaves a
damage register to claim against the company.

**The return is derived, never accumulated.** GSTR-1 is rebuilt from the
invoices and credit notes each time it is asked for, so it cannot drift from
the books. The reconciliation check proves it: the sections and the HSN summary
both tie to the ledger to the rupee, and the screen refuses to look clean when
they do not.

**A credit note to an unregistered buyer is not CDNUR.** CDNUR covers only
B2CL and exports; ordinary B2C returns are netted off inside the B2CS figures.
Getting this wrong is a common way to overstate outward supplies.

**Invoice numbers follow the e-invoicing rules anyway.** `BD/26-27/00001` — 14
characters, sequential and gapless within a financial year, never starting with
zero. Those rules are the portal's own constraints on a document number, so a
series that satisfies them can be filed or uploaded with nothing renumbered. A
van run number is exempt: it is an internal reference, not a GST document.

## What was taken out, and why

This started as a demonstration of breadth: 26 tables, 13 screens, targets,
visit logging, salesmen, e-invoicing, e-way bills. Most of it worked. Almost
none of it belonged in a one-owner business.

| Taken out | Why |
| --- | --- |
| **Targets** | He does not run against a plan. The dashboard now shows what sold, not what should have. |
| **Visits and no-order reasons** | Call logging is sales-management reporting for a team he does not have. |
| **Salesmen as a `User` entity** | The person with the van is a name written on the trip. There is no login, so there was never anything a role could mean. |
| **e-invoicing** | Applies above ₹5 crore turnover; this firm is well under. A locally computed IRN is not valid for filing, and shipping one invites someone to rely on it. |
| **e-way bills** | Raised on the government portal. **A van load over ₹50,000 still legally needs one** — it just happens outside this app. |
| **Calendar events** | Seeded content pretending to be a feature. The GSTR-1 due dates are computed. |
| **Load sheets (`Dispatch`), then beats** | Both made the owner plan a trip before he could bill anyone. A bill now says how it leaves, and the van run follows from the bills. |

The test suites now assert the *absence* of e-invoicing and e-way bills, so
neither can creep back unnoticed.

## The demo data

`python -m app.rebuild --demo --force` builds a business of roughly ₹1.6 crore
over the period, across 130-odd shops and 6 routes, with about six months of
trading history, ~2,000 invoices, 34 credit notes and a tail of overdue bills.
The shape is deterministic; the dates follow the calendar, so the current month
is never empty and the app never reads as dead.

It deliberately includes the messy parts: short-dated stock that could not be
cleared, one lot already expired, shops past their credit limit, interstate
sales that exercise the IGST path, and both GST slabs in the rate table.

Orders only go back a fortnight, on the premise that they started being
written down then while the office had been billing for months. Van runs are
reconstructed from the bills raised each day, which is exactly what a run is,
so nothing about them is invented.

The most recent run is left **open**, so the app opens on a van that still has
something to do rather than on a finished week. Today is often a Sunday in the
demo calendar, when the history generates no trading at all; without this the
Deliveries page would open empty.

## Not built yet

- **Alembic.** See "Changing the schema" above. This is the one that has to
  happen before real use.
- **Backups.** The business would be one SQLite file with no copy.
- **Login.** Anyone who reaches the machine can raise a bill.
- **Scheme engine.** The slab discounts, QPS and display schemes that drive
  most of the trade's margin are still entered by hand as a line discount or a
  free-goods line.
- **GSTR-3B and purchase-side reconciliation.** GSTR-1 is outward supplies
  only. Matching GSTR-2B against the purchase register to protect input credit
  is a separate job, and a valuable one.
- **Delivery sequencing.** The bills on a run are listed in the order they
  were raised, not in the order the van should drive them.
- **Proof of delivery.** A run goes `out` then `done`; there is no record of
  which shop actually received its goods, or when.
- **Van reconciliation.** Deliberately out, for the reasons under "The bill,
  and the van". Worth revisiting if stock keeps going missing.
- **Offline billing.** Raising a bill needs a live connection.

## Thresholds are settings, not constants

GST thresholds move. These live in `backend/app/config.py` rather than in the
code, and the shipped values are what applied when this was written —
**confirm each with his CA before go-live**:

| Setting | Shipped value | What it governs |
|---|---|---|
| `b2cl_threshold` | ₹1,00,000 | Interstate B2C above this goes to B2CL, not B2CS |
| `hsn_digits` | 6 | HSN digits required in Table 12 |

The GST rate itself is not here: it is dated data in the `gst_rates` table, so
historical invoices reprint at the rate that applied to them.

## Before this goes near a real business

- Add Alembic. The schema is created with `create_all` and changed by
  rebuilding, which destroys data.
- Take backups of the SQLite file, somewhere off the machine.
- Add a login before this leaves a trusted network.
- Confirm the GST rate, the derived PTR and PTD, and the opening stock.
- Fill in Setup → My firm completely. A bill printed without a GSTIN or a
  place of supply is not a tax invoice.
- For a hosted multi-user deployment move to PostgreSQL — the schema is written
  for it, so it is a URL change plus `pip install "psycopg[binary]"`.
