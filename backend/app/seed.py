"""Load a realistic demo dataset.

Models a single-owner biscuit distributorship in Hyderabad carrying the
supplier's catalogue in `catalogue.py`, with six months of history so the
dashboard
has something real to show. Everything is deterministic: the same seed
produces the same database.

    python -m app.seed            # rebuild from scratch
    python -m app.seed --keep     # only add if the database is empty

The generator runs in two passes. It first plans every order, then buys
enough stock ahead of each week to cover that plan, so FEFO allocation
never runs dry and the stock ledger stays internally consistent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .catalogue import CATALOGUE, SUPPLIER
from .database import Base, SessionLocal, engine
from .models import (
    Route,
    CompanyProfile,
    GstRate,
    Invoice,
    InvoiceLine,
    InvoiceLineBatch,
    Payment,
    PaymentAllocation,
    Product,
    Purchase,
    PurchaseLine,
    Retailer,
    StockBatch,
    StockLedger,
)
from .money import q2, q4
from . import seed_history
from .services import numbering, stock
from .services.gst import compute_line, compute_totals

#: The demo always runs up to the real today. Pinning this to a fixed date
#: meant that a week after seeding, the current month read zero and the app
#: looked broken -- which is exactly the figure someone judges it on.
TODAY = dt.date.today()

#: Five complete months plus the month in progress. Starts on a 1st so the
#: month-on-month comparison and the trend chart have whole periods to work
#: with, rather than a part-month at the far end that reads as a collapse.
HISTORY_START = (TODAY.replace(day=1) - dt.timedelta(days=150)).replace(day=1)
OPENING_STOCK_DATE = HISTORY_START - dt.timedelta(days=3)
HOME_STATE = "36"  # Telangana

#: Fixed, so the *shape* of the demo is reproducible even though the dates
#: move with the calendar: same mix of outlets, same order sizes, same
#: payment behaviour on any given run.
RNG_SEED = 20261023

#: Orders were only written down from a fortnight before "today"; invoices run
#: the whole history. Plenty of shops are still billed at the counter with no
#: order taken in advance.
ORDERS_SINCE = TODAY - dt.timedelta(days=14)


# --- master data -----------------------------------------------------------

# name, weekday (0 = Monday)
ROUTES = [
    ("Ameerpet", 0),
    ("Kukatpally", 1),
    ("Secunderabad", 2),
    ("Dilsukhnagar", 3),
    ("Mehdipatnam", 4),
    ("AP Outstation", 5),
]

# shop, owner, outlet type, route index, registered, credit days, credit limit
RETAILERS = [
    ("Sri Venkateswara Kirana", "V Narasimha", "kirana", 0, False, 7, 25000),
    ("Lakshmi General Stores", "K Lakshmi", "kirana", 0, False, 7, 30000),
    ("Anand Super Market", "Anand Rao", "supermarket", 0, True, 15, 150000),
    ("New Bombay Bakery", "Imran Khan", "bakery", 0, False, 7, 20000),
    ("Raj Pan Shop", "Rajesh", "pan_shop", 0, False, 0, 8000),
    ("Gayatri Stores", "G Padma", "kirana", 0, False, 7, 22000),
    ("Balaji Provisions", "B Srinivas", "kirana", 1, False, 7, 28000),
    ("SLN Stores", "S L Naidu", "kirana", 1, True, 15, 60000),
    ("Siddhartha Supermarket", "P Siddharth", "supermarket", 1, True, 15, 180000),
    ("Hanuman Kirana & General", "H Prasad", "kirana", 1, False, 7, 24000),
    ("Krishna Tea Stall", "K Murali", "tea_stall", 1, False, 0, 6000),
    ("Nandini Stores", "N Sujatha", "kirana", 1, False, 7, 20000),
    ("Deccan Mart", "Faisal Ahmed", "supermarket", 2, True, 21, 200000),
    ("Sai Ram General Stores", "M Ramesh", "kirana", 2, False, 7, 26000),
    ("Royal Bakery", "Joseph D", "bakery", 2, True, 15, 45000),
    ("Jai Jawan Kirana", "S Yadav", "kirana", 2, False, 7, 18000),
    ("Sunrise Departmental", "A Kiran", "supermarket", 2, True, 15, 120000),
    ("Metro Canteen Supplies", "R Shankar", "canteen", 2, True, 21, 90000),
    ("Bhavani Provisions", "B Kavitha", "kirana", 3, False, 7, 25000),
    ("Vijaya Stores", "V Prakash", "kirana", 3, False, 7, 21000),
    ("Annapurna Kirana", "A Sarala", "kirana", 3, False, 7, 19000),
    ("Green Leaf Organic", "N Meera", "supermarket", 3, True, 15, 80000),
    ("Pavan Kirana", "P Pavan", "kirana", 3, False, 7, 17000),
    ("Sri Durga Bakery", "D Satish", "bakery", 3, False, 7, 23000),
    ("More Fresh Supermarket", "T Vinod", "supermarket", 4, True, 21, 220000),
    ("Mehdipatnam Kirana Mart", "S Aslam", "kirana", 4, False, 7, 27000),
    ("Charminar Provisions", "M Yousuf", "kirana", 4, False, 7, 24000),
    ("Zam Zam Tea Stall", "A Rahim", "tea_stall", 4, False, 0, 7000),
    ("Shanti General Stores", "S Shanti", "kirana", 4, False, 7, 20000),
    ("Sagar Departmental", "K Sagar", "supermarket", 4, True, 15, 110000),
    ("Kurnool Trading Co", "N Ravindra", "supermarket", 5, True, 21, 160000),
    ("Vijayawada Bazaar", "Ch Murthy", "supermarket", 5, True, 21, 140000),
]

CITY_BY_ROUTE = {
    0: ("Ameerpet, Hyderabad", "500016", "Telangana", "36"),
    1: ("Kukatpally, Hyderabad", "500072", "Telangana", "36"),
    2: ("Secunderabad", "500003", "Telangana", "36"),
    3: ("Dilsukhnagar, Hyderabad", "500060", "Telangana", "36"),
    4: ("Mehdipatnam, Hyderabad", "500028", "Telangana", "36"),
    5: ("Kurnool", "518001", "Andhra Pradesh", "37"),
}

# A route covers 20-35 outlets in a day, so the named shops above are
# topped up to that density from these name parts. Without the volume, each
# retailer would have to absorb an implausible share of turnover and almost
# every one would sit over its credit limit.
SHOP_PREFIXES = [
    "Sri", "Sree", "New", "Royal", "Balaji", "Lakshmi", "Venkata", "Sai",
    "Krishna", "Ganesh", "Vijaya", "Anand", "Deccan", "Golden", "Star",
    "Bharat", "Jai", "Siddhi", "Amrutha", "Tirumala", "Nandi", "Shanti",
]
SHOP_CORES = [
    "Kirana", "General Stores", "Provisions", "Super Market", "Departmental",
    "Traders", "Agencies", "Stores", "Mart", "Bakery", "Tea Stall",
    "Fancy Store", "Daily Needs", "Family Mart",
]

#: A sub-distributor trades under a wholesaler's name, not a tea stall's. The
#: general pool is drawn independently of the outlet type, so wholesale draws
#: from this instead.
WHOLESALE_CORES = [
    "Traders", "Agencies", "Distributors", "Enterprises", "Trading Co",
    "Sales Agency", "Wholesale Mart",
]
OWNER_FIRST = [
    "Ramesh", "Suresh", "Prakash", "Satish", "Venkat", "Mohan", "Kiran",
    "Naveen", "Srinivas", "Mahesh", "Ravi", "Anil", "Sunil", "Rajesh",
    "Lakshmi", "Padma", "Sujatha", "Kavitha", "Sarala", "Meera", "Aslam",
    "Yousuf", "Imran", "Rahim", "Joseph", "Daniel",
]
OWNER_LAST = [
    "Reddy", "Rao", "Naidu", "Sharma", "Gupta", "Yadav", "Kumar", "Prasad",
    "Shetty", "Murthy", "Chary", "Goud", "Khan", "Ahmed", "Pillai",
]


def reset_schema() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed_company(db: Session) -> CompanyProfile:
    company = CompanyProfile(
        legal_name="Sri Lakshmi Agencies",
        trade_name="Sri Lakshmi Agencies",
        gstin="36ABCFS4321L1ZP",
        pan="ABCFS4321L",
        fssai_no="13322999000456",
        address_line1="Plot 42, Sai Nagar Industrial Area",
        address_line2="Balanagar",
        city="Hyderabad",
        state_name="Telangana",
        state_code=HOME_STATE,
        pincode="500037",
        phone="040-23456789",
        email="billing@srilakshmiagencies.in",
        bank_name="State Bank of India, Balanagar",
        bank_account="30127845963",
        bank_ifsc="SBIN0004321",
        invoice_prefix="BD",
    )
    db.add(company)
    db.flush()
    return company


def seed_gst_rates(db: Session) -> None:
    """Both slabs biscuits have sat in, so dated lookup is exercised."""
    db.add_all(
        [
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
    )
    db.flush()


def seed_routes(db: Session) -> list[Route]:
    """The standing routes. Who drives them is decided per trip, not here."""
    routes = []
    for name, dow in ROUTES:
        route = Route(name=name, day_of_week=dow)
        db.add(route)
        routes.append(route)
    db.flush()
    return routes


#: The depot a purchase is booked against. One supplier now, not three.
SUPPLIER_DEPOT = f"{SUPPLIER} - cluster depot"

#: What a shop pays him. The order sheet states his cost, not his selling
#: price, so PTR is worked back from MRP the way the trade quotes it: strip
#: the GST out of MRP, then take the retailer's margin off what is left.
#: CONFIRM against his own rate card -- it is an assumption, not sheet data.
RETAILER_MARGIN = Decimal("0.12")

#: What a sub-distributor pays him: a thin markup on his own landing cost,
#: since he is passing the goods on rather than servicing the shop. Also an
#: assumption, not from the sheet. CONFIRM.
SUB_DISTRIBUTOR_MARKUP = Decimal("1.04")

#: MRP includes GST at the biscuit slab.
GST_DIVISOR = Decimal("1.05")


def seed_products(db: Session) -> list[Product]:
    """Load the supplier's catalogue and fill in the two prices it omits.

    The order sheet gives MRP, the pack, and the basic rate the company
    charges per case. That rate is his cost. It does not say what he charges
    a shop or a sub-distributor, so:

      PTR = MRP, less GST, less the retailer's margin
      PTD = his landing cost plus a thin markup

    Both derived figures are editable per SKU in Masters, which is where his
    real rate card should go once he confirms it.
    """
    products = []
    for (
        sku,
        brand,
        name,
        pack_g,
        per_case,
        mrp,
        landing,
        scheme_pct,
        case_kg,
        shelf,
        _vel,
    ) in CATALOGUE:
        mrp_d = Decimal(str(mrp))
        ptr = q4(mrp_d / GST_DIVISOR / (1 + RETAILER_MARGIN))
        ptd = q4(landing * SUB_DISTRIBUTOR_MARKUP)
        if ptd >= ptr:
            raise ValueError(
                f"{sku}: PTD {ptd} is not below PTR {ptr}; a sub-distributor "
                "would pay more than a shop."
            )
        if ptr >= mrp_d / GST_DIVISOR:
            raise ValueError(f"{sku}: PTR {ptr} leaves the shop no margin.")
        product = Product(
            sku_code=sku,
            brand=brand,
            name=name,
            pack_size_g=pack_g,
            pieces_per_case=per_case,
            hsn="1905",
            mrp=mrp_d,
            ptr=ptr,
            ptd=ptd,
            landing_rate=landing,
            purchase_scheme_pct=Decimal(str(scheme_pct)),
            # The company's scheme is what he receives, not what he gives, so
            # nothing is pre-filled on his bills. He sets this per SKU once he
            # decides how much of the scheme he passes on.
            default_discount_pct=Decimal("0"),
            shelf_life_days=shelf,
            case_weight_kg=case_kg,
        )
        db.add(product)
        products.append(product)
    db.flush()
    return products


#: Outlets per route, so each route day is a realistic day's work.
RETAILERS_PER_ROUTE = {0: 24, 1: 24, 2: 26, 3: 24, 4: 24, 5: 8}

# outlet type -> (share of outlets, credit days, credit limit range)
OUTLET_PROFILE = {
    "kirana": (0.58, 7, (15000, 40000)),
    "supermarket": (0.12, 15, (120000, 260000)),
    "bakery": (0.10, 7, (25000, 50000)),
    "tea_stall": (0.08, 0, (5000, 12000)),
    "pan_shop": (0.05, 0, (6000, 14000)),
    "canteen": (0.04, 21, (60000, 110000)),
    # A sub-distributor: buys by the pallet at PTD and resells onward.
    "wholesale": (0.03, 21, (200000, 450000)),
}


def seed_retailers(db: Session, routes: list[Route], rng: random.Random) -> list[Retailer]:
    """The named shops, topped up to a realistic density per route."""
    planned: list[tuple[str, str, str, int, int, int]] = []
    #     shop, owner, outlet type, route index, credit days, credit limit

    for shop, owner, outlet, route_idx, registered, cr_days, cr_limit in RETAILERS:
        planned.append((shop, owner, outlet, route_idx, cr_days, cr_limit))

    named_per_route: dict[int, int] = defaultdict(int)
    for _s, _o, _t, route_idx, _d, _l in planned:
        named_per_route[route_idx] += 1

    outlet_types = list(OUTLET_PROFILE)
    outlet_weights = [OUTLET_PROFILE[t][0] for t in outlet_types]
    used_names = {shop for shop, *_ in planned}

    for route_idx, wanted in RETAILERS_PER_ROUTE.items():
        for _ in range(max(wanted - named_per_route[route_idx], 0)):
            outlet = rng.choices(outlet_types, weights=outlet_weights)[0]
            cores = WHOLESALE_CORES if outlet == "wholesale" else SHOP_CORES
            for _attempt in range(40):
                name = f"{rng.choice(SHOP_PREFIXES)} {rng.choice(cores)}"
                if name not in used_names:
                    break
            else:
                name = f"{rng.choice(SHOP_PREFIXES)} {rng.choice(cores)} II"
            used_names.add(name)
            _share, cr_days, (low, high) = OUTLET_PROFILE[outlet]
            planned.append((
                name,
                f"{rng.choice(OWNER_FIRST)} {rng.choice(OWNER_LAST)}",
                outlet,
                route_idx,
                cr_days,
                rng.randrange(low, high + 1, 1000),
            ))

    rng.shuffle(planned)
    retailers = []
    for index, (shop, owner, outlet, route_idx, cr_days, cr_limit) in enumerate(
        planned, start=1
    ):
        city, pin, state_name, state_code = CITY_BY_ROUTE[route_idx]
        # Bigger formats are registered; most small kiranas are not.
        registered = outlet in ("supermarket", "canteen", "wholesale") or (
            outlet == "bakery" and rng.random() < 0.4
        )
        gstin = (
            f"{state_code}AAACR{3000 + index:04d}Q1Z{rng.randint(1, 9)}"
            if registered
            else None
        )
        # A handful of buyers are sub-distributors rather than shops: they
        # buy at PTD and resell onward, which is the second kind of customer
        # this business actually has.
        party_type = "distributor" if outlet == "wholesale" else "retailer"
        # An unregistered shop usually negotiates one all-in rate per case
        # rather than a rate plus tax. Registered buyers want the tax shown
        # separately, because they are claiming it back.
        price_mode = (
            "inclusive"
            if not registered and party_type == "retailer" and rng.random() < 0.35
            else "exclusive"
        )
        # Most shops are long-standing; a handful were opened recently, so
        # "new retailers this month" is a figure that actually moves.
        if rng.random() < 0.08:
            created = TODAY - dt.timedelta(days=rng.randint(1, 100))
        else:
            created = HISTORY_START - dt.timedelta(days=rng.randint(30, 900))

        retailers.append(
            Retailer(
                code=f"R{index:04d}",
                shop_name=shop,
                owner_name=owner,
                gstin=gstin,
                is_registered=registered,
                phone=f"9{rng.randint(400000000, 899999999)}",
                address_line=f"{rng.randint(1, 180)}-{rng.randint(1, 60)}, {city}",
                city=city.split(",")[0],
                state_name=state_name,
                state_code=state_code,
                pincode=pin,
                outlet_type=outlet,
                party_type=party_type,
                price_mode=price_mode,
                route_id=routes[route_idx].id,
                credit_limit=Decimal(cr_limit),
                credit_days=cr_days,
                created_on=created,
            )
        )
    db.add_all(retailers)
    db.flush()
    return retailers


# --- sales planning --------------------------------------------------------


def selling_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every day in range except Sunday."""
    days, cursor = [], start
    while cursor <= end:
        if cursor.weekday() != 6:
            days.append(cursor)
        cursor += dt.timedelta(days=1)
    return days


#: Seasonal lifts, as (month, from-day, to-day, multiplier). Kept as
#: month-and-day rather than full dates because the history window now moves
#: with the calendar: a fixed 2026 date would simply fall outside it next year
#: and the demo would flatten out.
#:
#: The dates are approximate. Diwali in particular is lunar and moves by weeks
#: year to year; this is the usual late-October build-up, not a calendar.
SEASONAL_LIFTS = (
    (10, 12, 31, 1.45),  # Diwali gifting build-up
    (11, 1, 8, 1.45),    # and its tail into November
    (6, 8, 25, 1.20),    # schools reopening
    (8, 20, 30, 1.15),   # Rakhi / Ganesh Chaturthi
)


def festival_multiplier(day: dt.date) -> float:
    """Biscuit demand lifts before Diwali and when schools reopen."""
    for month, start_day, end_day, lift in SEASONAL_LIFTS:
        if day.month == month and start_day <= day.day <= end_day:
            return lift
    return 1.0


def plan_orders(
    products: list[Product],
    retailers: list[Retailer],
    routes: list[Route],
    rng: random.Random,
) -> list[dict]:
    """Decide who orders what on which day, before any stock is bought."""
    by_route: dict[int, list[Retailer]] = defaultdict(list)
    for retailer in retailers:
        by_route[retailer.route_id].append(retailer)

    route_by_weekday = {route.day_of_week: route for route in routes}
    velocities = [row[10] for row in CATALOGUE]

    plan: list[dict] = []
    for day in selling_days(HISTORY_START, TODAY):
        route = route_by_weekday.get(day.weekday())
        if route is None:
            continue
        lift = festival_multiplier(day)

        for retailer in by_route[route.id]:
            # Bigger outlets order nearly every visit. A small kirana often
            # still has stock and waves the van off, so it buys closer
            # to fortnightly than weekly.
            base = {
                "supermarket": 0.85,
                "canteen": 0.70,
                "bakery": 0.60,
                "kirana": 0.50,
                "tea_stall": 0.35,
                "pan_shop": 0.30,
                "wholesale": 0.80,
            }[retailer.outlet_type]
            if rng.random() > min(base * lift, 0.97):
                # This shop does not buy on this run. It still has stock, or
                # the owner was out -- either way, nothing is billed.
                continue

            size = {
                "supermarket": (6, 11),
                "canteen": (4, 8),
                "bakery": (3, 6),
                "kirana": (3, 7),
                "tea_stall": (2, 4),
                "pan_shop": (2, 4),
                "wholesale": (7, 13),
            }[retailer.outlet_type]
            line_count = rng.randint(*size)
            chosen = _weighted_sample(products, velocities, line_count, rng)

            # A kirana buys biscuits in ones and twos of a case, not by the
            # pallet. Against the real catalogue these multipliers produce a
            # kirana bill near Rs 3.3k and a supermarket near Rs 11.6k, and
            # 130 outlets at those sizes put the business around Rs 2.25 crore
            # a year. It is lower than the earlier invented catalogue implied
            # because this one is mostly Rs 5 and Rs 10 packs.
            scale = {
                "supermarket": 2.2,
                "canteen": 1.7,
                "bakery": 1.1,
                "kirana": 0.9,
                "tea_stall": 0.5,
                "pan_shop": 0.4,
                # A sub-distributor buys to resell to his own shops, so he
                # lifts far more per visit than any single outlet. At the real
                # catalogue's price points 4.0 put him at Rs 23k a bill, which
                # is retail-sized and also never crossed the Rs 50,000 e-way
                # threshold, so that whole path went untested.
                "wholesale": 9.0,
            }[retailer.outlet_type]

            lines = []
            for product in chosen:
                cases = max(1, int(round(rng.uniform(0.4, 1.8) * scale * lift)))
                loose = rng.choice([0, 0, 0, product.pieces_per_case // 4])
                qty = cases * product.pieces_per_case + loose
                # A slab discount shows up on roughly one line in eight.
                discount_pct = (
                    Decimal(str(rng.choice([2, 3, 5]))) if rng.random() < 0.12 else None
                )
                lines.append(
                    {
                        "product": product,
                        "cases": cases,
                        "loose": loose,
                        "qty": qty,
                        "discount_pct": discount_pct,
                        "is_free": False,
                    }
                )

            # Scheme giveaway: one free case of the biggest line now and then.
            if rng.random() < 0.09 and lines:
                biggest = max(lines, key=lambda line: line["qty"])
                product = biggest["product"]
                lines.append(
                    {
                        "product": product,
                        "cases": 1,
                        "loose": 0,
                        "qty": product.pieces_per_case,
                        "discount_pct": None,
                        "is_free": True,
                    }
                )

            plan.append(
                {
                    "date": day,
                    "retailer": retailer,
                    "lines": lines,
                }
            )
    return plan


def _weighted_sample(
    products: list[Product], weights: list[float], k: int, rng: random.Random
) -> list[Product]:
    """Pick k distinct products, favouring fast movers."""
    pool = list(zip(products, weights, strict=True))
    picked = []
    k = min(k, len(pool))
    for _ in range(k):
        total = sum(w for _, w in pool)
        mark = rng.uniform(0, total)
        running = 0.0
        for index, (product, weight) in enumerate(pool):
            running += weight
            if running >= mark:
                picked.append(product)
                pool.pop(index)
                break
    return picked


# --- purchasing to cover the plan -----------------------------------------


def seed_purchases(
    db: Session, plan: list[dict], products: list[Product], rng: random.Random
) -> dict[int, list[StockBatch]]:
    """Buy stock weekly, ahead of the orders that week, plus opening stock.

    The indent brings stock *up to* about a week and a quarter of cover
    rather than ordering a fixed multiple of demand every week. Ordering a
    multiple regardless of what is already on the racks is what leaves a
    distributor sitting on two months of biscuits; this way cover stays
    realistic and slow movers age naturally into the near-expiry bucket.
    """
    weekly_demand: dict[tuple[dt.date, int], int] = defaultdict(int)
    for order in plan:
        monday = order["date"] - dt.timedelta(days=order["date"].weekday())
        for line in order["lines"]:
            weekly_demand[(monday, line["product"].id)] += line["qty"]

    product_by_id = {p.id: p for p in products}
    batches_by_product: dict[int, list[StockBatch]] = defaultdict(list)
    batch_counter: dict[int, int] = defaultdict(int)

    def make_batch(
        product: Product, received_on: dt.date, pieces: int, age_days: int
    ) -> StockBatch:
        batch_counter[product.id] += 1
        mfg = received_on - dt.timedelta(days=age_days)
        batch = StockBatch(
            product_id=product.id,
            batch_no=f"{mfg:%y%m}{batch_counter[product.id]:02d}",
            mfg_date=mfg,
            expiry_date=mfg + dt.timedelta(days=product.shelf_life_days),
            cost_per_piece=product.ptd,
        )
        db.add(batch)
        db.flush()
        batches_by_product[product.id].append(batch)
        return batch

    # Running on-hand per product, so each indent can look at the racks
    # before deciding what to order.
    on_hand: dict[int, int] = defaultdict(int)

    # Opening stock: roughly a week of cover, bought old enough that the
    # slower movers are near expiry by today.
    first_week = min(monday for monday, _ in weekly_demand)
    for (monday, product_id), pieces in sorted(weekly_demand.items()):
        if monday != first_week:
            continue
        product = product_by_id[product_id]
        per_case = product.pieces_per_case
        qty = max(1, -(-int(pieces * 1.1) // per_case)) * per_case
        batch = make_batch(product, OPENING_STOCK_DATE, qty, rng.randint(150, 190))
        stock.post_movement(
            db,
            product_id=product.id,
            batch_id=batch.id,
            qty_pieces=qty,
            reason="opening",
            occurred_on=OPENING_STOCK_DATE,
            note="Opening stock carried in at go-live",
        )
        on_hand[product.id] += qty

    # Weekly indents, received the Saturday before the week they cover.
    weeks = sorted({m for m, _ in weekly_demand})
    for position, monday in enumerate(weeks):
        received_on = monday - dt.timedelta(days=2)
        if received_on < OPENING_STOCK_DATE:
            received_on = OPENING_STOCK_DATE + dt.timedelta(days=1)

        per_brand: dict[str, list[tuple[Product, int]]] = defaultdict(list)
        for (week, product_id), pieces in weekly_demand.items():
            if week != monday:
                continue
            product = product_by_id[product_id]
            per_case = product.pieces_per_case
            # Aim to hold this week plus next, with a little over. That keeps
            # cover around two weeks at indent and one week by Saturday,
            # which is the band a biscuit distributor actually runs at.
            follow_on = (
                weekly_demand.get((weeks[position + 1], product_id), 0)
                if position + 1 < len(weeks)
                else pieces
            )
            wanted_cover = int((pieces + follow_on) * 1.25)
            shortfall = wanted_cover - on_hand[product.id]
            if shortfall <= 0:
                continue  # enough on the racks already; skip the line
            qty = max(1, -(-shortfall // per_case)) * per_case
            on_hand[product.id] += qty
            per_brand[product.brand].append((product, qty))

        # This week's orders then leave the godown.
        for (week, product_id), pieces in weekly_demand.items():
            if week == monday:
                on_hand[product_id] = max(on_hand[product_id] - pieces, 0)

        if not per_brand:
            continue

        for brand, items in per_brand.items():
            purchase = Purchase(
                grn_no=numbering.next_grn_no(db, received_on),
                supplier_name=SUPPLIER_DEPOT,
                company_invoice_no=f"{brand[:3].upper()}/{received_on:%y%m%d}/"
                f"{rng.randint(1000, 9999)}",
                company_invoice_date=received_on - dt.timedelta(days=1),
                received_on=received_on,
                note=f"Weekly indent for week of {monday:%d-%b-%Y}",
            )
            db.add(purchase)
            db.flush()

            taxable_total = Decimal("0.00")
            tax_total = Decimal("0.00")
            for product, pieces in items:
                age = rng.randint(8, 26)
                batch = make_batch(product, received_on, pieces, age)
                line_calc = compute_line(
                    qty_pieces=pieces,
                    rate_per_piece=Decimal(str(product.ptd)),
                    gst_rate=Decimal("5"),
                    is_interstate=False,
                )
                db.add(
                    PurchaseLine(
                        purchase_id=purchase.id,
                        product_id=product.id,
                        batch_id=batch.id,
                        cases=pieces // product.pieces_per_case,
                        loose_pieces=pieces % product.pieces_per_case,
                        qty_pieces=pieces,
                        rate_per_piece=product.ptd,
                        taxable=line_calc.taxable,
                        gst_rate=Decimal("5"),
                        tax_amount=line_calc.tax,
                        line_total=line_calc.line_total,
                    )
                )
                stock.post_movement(
                    db,
                    product_id=product.id,
                    batch_id=batch.id,
                    qty_pieces=pieces,
                    reason="grn",
                    occurred_on=received_on,
                    ref_type="purchase",
                    ref_id=purchase.id,
                )
                taxable_total += line_calc.taxable
                tax_total += line_calc.tax

            purchase.taxable_total = q2(taxable_total)
            purchase.tax_total = q2(tax_total)
            purchase.grand_total = q2(taxable_total + tax_total)
            db.flush()

    _seed_stuck_stock(
        db, weekly_demand, product_by_id, make_batch, rng
    )
    return batches_by_product


def _seed_stuck_stock(
    db: Session,
    weekly_demand: dict[tuple[dt.date, int], int],
    product_by_id: dict[int, Product],
    make_batch,
    rng: random.Random,
) -> None:
    """Add the near-expiry pile every distributor actually carries.

    Companies push short-dated stock through quarterly schemes, and a
    distributor who takes the deal on a slow mover is left holding it. The
    batch arrives already part-way through its shelf life and demand since
    then cannot absorb the quantity, so a remainder ages into the
    near-expiry and expired buckets. FEFO still sells it first.
    """
    weekly_total: dict[int, int] = defaultdict(int)
    weeks_seen: dict[int, int] = defaultdict(int)
    for (_week, product_id), pieces in weekly_demand.items():
        weekly_total[product_id] += pieces
        weeks_seen[product_id] += 1

    # The slowest movers are the ones that get stuck.
    slowest = sorted(
        weekly_total,
        key=lambda pid: weekly_total[pid] / max(weeks_seen[pid], 1),
    )[:7]

    received_on = TODAY - dt.timedelta(days=26)
    purchase = Purchase(
        grn_no=numbering.next_grn_no(db, received_on),
        supplier_name="Mixed - quarterly scheme allocation",
        company_invoice_no=f"SCHEME/{received_on:%y%m%d}/{rng.randint(1000, 9999)}",
        company_invoice_date=received_on - dt.timedelta(days=2),
        received_on=received_on,
        note="Quarterly scheme allocation taken on short-dated stock. "
        "Clear on priority before expiry.",
    )
    db.add(purchase)
    db.flush()

    taxable_total = Decimal("0.00")
    tax_total = Decimal("0.00")
    for position, product_id in enumerate(slowest):
        product = product_by_id[product_id]
        weekly = max(weekly_total[product_id] // max(weeks_seen[product_id], 1), 1)
        per_case = product.pieces_per_case
        qty = max(1, -(-(weekly * 8) // per_case)) * per_case

        # One lot has already tipped over; the rest expire in the coming weeks.
        days_left = -rng.randint(2, 9) if position == 0 else rng.randint(18, 78)
        expiry = TODAY + dt.timedelta(days=days_left)
        age_at_receipt = (received_on - (expiry - dt.timedelta(days=product.shelf_life_days))).days

        batch = make_batch(product, received_on, qty, age_at_receipt)
        line_calc = compute_line(
            qty_pieces=qty,
            rate_per_piece=Decimal(str(product.ptd)),
            gst_rate=Decimal("5"),
            is_interstate=False,
        )
        db.add(
            PurchaseLine(
                purchase_id=purchase.id,
                product_id=product.id,
                batch_id=batch.id,
                cases=qty // per_case,
                loose_pieces=qty % per_case,
                qty_pieces=qty,
                rate_per_piece=product.ptd,
                taxable=line_calc.taxable,
                gst_rate=Decimal("5"),
                tax_amount=line_calc.tax,
                line_total=line_calc.line_total,
            )
        )
        stock.post_movement(
            db,
            product_id=product.id,
            batch_id=batch.id,
            qty_pieces=qty,
            reason="grn",
            occurred_on=received_on,
            ref_type="purchase",
            ref_id=purchase.id,
            note="Short-dated scheme stock",
        )
        taxable_total += line_calc.taxable
        tax_total += line_calc.tax

    purchase.taxable_total = q2(taxable_total)
    purchase.tax_total = q2(tax_total)
    purchase.grand_total = q2(taxable_total + tax_total)
    db.flush()


# --- invoicing -------------------------------------------------------------


def seed_invoices(
    db: Session,
    company: CompanyProfile,
    plan: list[dict],
    batches_by_product: dict[int, list[StockBatch]],
    rng: random.Random,
) -> list[Invoice]:
    """Raise an invoice per planned order, allocating stock FEFO."""
    balances: dict[int, int] = dict(
        db.execute(
            select(StockLedger.batch_id, func.sum(StockLedger.qty_pieces)).group_by(
                StockLedger.batch_id
            )
        ).all()
    )
    # A batch is only sellable from the day it was received, so an invoice
    # early in the history cannot draw on stock that arrived months later.
    received_on_by_batch = stock.first_inward_dates(db)

    invoices = []
    skipped_lines = 0
    for order in sorted(plan, key=lambda o: (o["date"], o["retailer"].id)):
        day = order["date"]
        retailer = order["retailer"]
        interstate = retailer.state_code != company.state_code
        inclusive = retailer.price_mode == "inclusive"
        is_distributor = retailer.party_type == "distributor"

        computed, line_specs = [], []
        for spec in order["lines"]:
            product = spec["product"]
            qty = spec["qty"]
            available = [
                batch
                for batch in batches_by_product[product.id]
                if received_on_by_batch.get(batch.id, dt.date.max) <= day
            ]
            try:
                allocation = stock.plan_fefo(
                    available, balances, qty, day, product.display_name
                )
            except stock.InsufficientStock:
                skipped_lines += 1
                continue  # skip rather than oversell; the buffer makes this rare

            rate = Decimal(str(product.ptd if is_distributor else product.ptr))
            if inclusive:
                rate = q2(rate * Decimal("1.05"))
            discount = Decimal("0.00")
            if spec["discount_pct"] is not None and not spec["is_free"]:
                discount = q2(rate * qty * spec["discount_pct"] / 100)

            calc = compute_line(
                qty_pieces=qty,
                rate_per_piece=rate,
                gst_rate=Decimal("5"),
                discount=discount,
                is_interstate=interstate,
                is_free=spec["is_free"],
                price_inclusive=inclusive,
            )
            computed.append(calc)
            line_specs.append((spec, allocation, calc))
            for batch_id, taken in allocation:
                balances[batch_id] = balances.get(batch_id, 0) - taken

        if not line_specs:
            continue

        totals = compute_totals(computed, [s[0]["product"].hsn for s in line_specs])
        invoice = Invoice(
            invoice_no=numbering.next_invoice_no(db, day, company.invoice_prefix),
            invoice_date=day,
            retailer_id=retailer.id,
            place_of_supply=retailer.state_code,
            is_interstate=interstate,
            price_mode=retailer.price_mode,
            due_date=day + dt.timedelta(days=retailer.credit_days),
            taxable_total=totals.taxable_total,
            discount_total=totals.discount_total,
            cgst_total=totals.cgst_total,
            sgst_total=totals.sgst_total,
            igst_total=totals.igst_total,
            round_off=totals.round_off,
            grand_total=totals.grand_total,
            status="issued",
        )
        db.add(invoice)
        db.flush()

        for spec, allocation, calc in line_specs:
            product = spec["product"]
            line = InvoiceLine(
                invoice_id=invoice.id,
                product_id=product.id,
                hsn=product.hsn,
                cases=spec["cases"],
                loose_pieces=spec["loose"],
                qty_pieces=spec["qty"],
                rate_per_piece=calc.rate_per_piece,
                quoted_rate_per_piece=calc.quoted_rate,
                gross=calc.gross,
                discount=calc.discount,
                taxable=calc.taxable,
                gst_rate=calc.gst_rate,
                cgst=calc.cgst,
                sgst=calc.sgst,
                igst=calc.igst,
                line_total=calc.line_total,
                is_free=spec["is_free"],
            )
            db.add(line)
            db.flush()
            for batch_id, taken in allocation:
                db.add(
                    InvoiceLineBatch(
                        invoice_line_id=line.id, batch_id=batch_id, qty_pieces=taken
                    )
                )
                stock.post_movement(
                    db,
                    product_id=product.id,
                    batch_id=batch_id,
                    qty_pieces=-taken,
                    reason="sale",
                    occurred_on=day,
                    ref_type="invoice",
                    ref_id=invoice.id,
                )
        invoices.append(invoice)

    db.flush()
    if skipped_lines:
        print(f"  note: {skipped_lines} planned lines skipped for want of stock")
    return invoices


# --- collections -----------------------------------------------------------


def seed_payments(
    db: Session, invoices: list[Invoice], retailers: list[Retailer], rng: random.Random
) -> None:
    """Settle most invoices, leaving a believable ageing profile.

    Recent invoices are mostly still within credit, older ones mostly paid,
    and a tail of genuinely overdue ones remains so the ageing buckets and
    credit-limit warnings have something real to show.
    """
    retailer_by_id = {r.id: r for r in retailers}
    by_retailer: dict[int, list[Invoice]] = defaultdict(list)
    for invoice in invoices:
        by_retailer[invoice.retailer_id].append(invoice)

    events: list[tuple[dt.date, int, list[tuple[Invoice, Decimal]], str]] = []
    for retailer_id, retailer_invoices in by_retailer.items():
        retailer = retailer_by_id[retailer_id]
        pending: list[tuple[Invoice, Decimal]] = []
        pending_due: dt.date | None = None

        for invoice in sorted(retailer_invoices, key=lambda i: i.invoice_date):
            settle_on = invoice.due_date + dt.timedelta(days=rng.randint(-2, 5))
            if settle_on > TODAY:
                continue  # still within credit, nothing collected yet

            # Old bills get chased until they clear, so arrears concentrate in
            # the recent weeks instead of piling up across the whole history.
            days_overdue = (TODAY - invoice.due_date).days
            chased = days_overdue > 60
            unpaid_odds = 0.02 if chased else 0.06
            partial_odds = unpaid_odds + (0.03 if chased else 0.08)

            roll = rng.random()
            if roll < unpaid_odds:
                continue  # written-off tail
            if roll < partial_odds:
                share = rng.choice([0.5, 0.6, 0.75]) if chased else rng.choice(
                    [0.4, 0.5, 0.6, 0.75]
                )
                part = q2(Decimal(str(invoice.grand_total)) * Decimal(str(share)))
                events.append((settle_on, retailer_id, [(invoice, part)], "part"))
                continue

            pending.append((invoice, Decimal(str(invoice.grand_total))))
            if pending_due is None:
                pending_due = settle_on
            # Shopkeepers tend to clear a few bills together on one visit.
            if len(pending) >= rng.randint(1, 3):
                events.append((max(pending_due, settle_on), retailer_id, pending, "full"))
                pending, pending_due = [], None

        if pending:
            events.append((pending_due or TODAY, retailer_id, pending, "full"))

    for settle_on, retailer_id, items, kind in sorted(events, key=lambda e: e[0]):
        if settle_on > TODAY:
            settle_on = TODAY
        total = q2(sum(amount for _, amount in items))
        if total <= 0:
            continue
        retailer = retailer_by_id[retailer_id]
        mode = rng.choices(
            ["cash", "upi", "cheque", "bank_transfer"],
            weights=[0.45, 0.3, 0.15, 0.10] if not retailer.is_registered else [0.2, 0.3, 0.2, 0.3],
        )[0]
        reference = {
            "cash": None,
            "upi": f"UPI{rng.randint(10**9, 10**10 - 1)}",
            "cheque": f"CHQ{rng.randint(100000, 999999)}",
            "bank_transfer": f"NEFT{rng.randint(10**8, 10**9 - 1)}",
        }[mode]

        payment = Payment(
            receipt_no=numbering.next_receipt_no(db, settle_on),
            retailer_id=retailer_id,
            payment_date=settle_on,
            mode=mode,
            amount=total,
            reference=reference,
            note="Part payment" if kind == "part" else None,
        )
        db.add(payment)
        db.flush()
        for invoice, amount in items:
            db.add(
                PaymentAllocation(
                    payment_id=payment.id, invoice_id=invoice.id, amount=q2(amount)
                )
            )
    db.flush()


# --- targets and the calendar ---------------------------------------------


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    end = (
        dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    )
    return start, end


def run(keep_existing: bool = False) -> dict:
    if keep_existing:
        Base.metadata.create_all(engine)
        with SessionLocal() as probe:
            if probe.execute(select(func.count(Invoice.id))).scalar_one():
                return {"skipped": True}
    else:
        reset_schema()

    rng = random.Random(RNG_SEED)
    with SessionLocal() as db:
        company = seed_company(db)
        seed_gst_rates(db)
        routes = seed_routes(db)
        products = seed_products(db)
        retailers = seed_retailers(db, routes, rng)

        plan = plan_orders(products, retailers, routes, rng)
        batches_by_product = seed_purchases(db, plan, products, rng)
        invoices = seed_invoices(db, company, plan, batches_by_product, rng)
        order_stats = seed_history.seed_order_history(
            db,
            plan=plan,
            invoices=invoices,
            today=TODAY,
            orders_since=ORDERS_SINCE,
            rng=rng,
        )
        credit_notes = seed_history.seed_credit_notes(
            db, invoices=invoices, today=TODAY, rng=rng
        )
        seed_payments(db, invoices, retailers, rng)
        db.commit()

        summary = {
            "products": len(products),
            "retailers": len(retailers),
            "routes": len(routes),
            "purchases": db.execute(select(func.count(Purchase.id))).scalar_one(),
            "batches": db.execute(select(func.count(StockBatch.id))).scalar_one(),
            "ledger_rows": db.execute(select(func.count(StockLedger.id))).scalar_one(),
            "invoices": len(invoices),
            "invoice_lines": db.execute(
                select(func.count(InvoiceLine.id))
            ).scalar_one(),
            "payments": db.execute(select(func.count(Payment.id))).scalar_one(),
            "orders": order_stats["orders"],
            "pending_orders": order_stats["pending_orders"],
            "deliveries": order_stats["deliveries"],
            "credit_notes": credit_notes,
            "sales_value": float(
                db.execute(select(func.sum(Invoice.grand_total))).scalar_one() or 0
            ),
            "collected": float(
                db.execute(select(func.sum(Payment.amount))).scalar_one() or 0
            ),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo dataset.")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave an existing non-empty database alone",
    )
    args = parser.parse_args()
    result = run(keep_existing=args.keep)
    if result.get("skipped"):
        print("Database already has invoices; left untouched.")
        return
    width = max(len(k) for k in result)
    for key, value in result.items():
        shown = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
        print(f"{key.replace('_', ' '):<{width}}  {shown}")


if __name__ == "__main__":
    main()
