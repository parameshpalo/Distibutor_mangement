"""Masters: company profile, products, retailers, routes, GST rates."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Route,
    CompanyProfile,
    GstRate,
    InvoiceLine,
    Product,
    Retailer,
    StockLedger,
)
from ..schemas import (
    RouteOut,
    CompanyIn,
    CompanyOut,
    ProductIn,
    ProductOut,
    ProductPatch,
    RetailerIn,
    RetailerOut,
    RetailerPatch,
)
from ..services import stock
from ..services.gst import rate_for_hsn


def _require_rate(db: Session, hsn: str) -> None:
    """Refuse an HSN with no rate now, rather than at the first sale.

    `rate_for_hsn` signals a missing rate with ValueError, which would
    otherwise surface as a 500. It is the caller's input that is wrong, so
    it is a 422 and the message names the fix.
    """
    try:
        rate_for_hsn(db, hsn, dt.date.today())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

router = APIRouter(prefix="/api", tags=["masters"])


@router.get("/company", response_model=CompanyOut)
def get_company(db: Session = Depends(get_db)):
    profile = db.execute(select(CompanyProfile).limit(1)).scalar_one_or_none()
    if profile is None:
        raise HTTPException(404, "Company profile has not been set up yet.")
    return profile


@router.patch("/company", response_model=CompanyOut)
def update_company(payload: CompanyIn, db: Session = Depends(get_db)):
    """Save the firm's own details.

    These print on every tax invoice, so the GSTIN is checked for shape and
    the state code is derived from it rather than typed. Changing the invoice
    prefix does not renumber anything already issued -- the series carries on
    from where it is, under the new prefix.
    """
    profile = db.execute(select(CompanyProfile).limit(1)).scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            404,
            "There is no company profile. Run `python -m app.init` to start "
            "a database.",
        )

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "gstin" in changes:
        gstin = changes["gstin"].strip().upper()
        if not gstin.isalnum():
            raise HTTPException(422, "A GSTIN is 15 letters and digits only.")
        changes["gstin"] = gstin
        state_code = gstin[:2]
        if not state_code.isdigit():
            raise HTTPException(
                422, f"'{state_code}' is not a state code; a GSTIN starts with two digits."
            )
        changes["state_code"] = state_code

    for field, value in changes.items():
        setattr(profile, field, value.strip() if isinstance(value, str) else value)

    db.commit()
    db.refresh(profile)
    return profile


@router.get("/products", response_model=list[ProductOut])
def list_products(
    search: str | None = None,
    brand: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    stmt = select(Product)
    if active_only:
        stmt = stmt.where(Product.is_active)
    if brand:
        stmt = stmt.where(Product.brand == brand)
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(needle),
                Product.sku_code.ilike(needle),
                Product.brand.ilike(needle),
            )
        )
    products = db.execute(stmt.order_by(Product.brand, Product.name)).scalars().all()
    return [
        ProductOut.model_validate(p).model_copy(
            update={"name": p.display_name}
        )
        for p in products
    ]


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, payload: ProductPatch, db: Session = Depends(get_db)
):
    """Change a product in place.

    Prices are read fresh on every bill, so an edit here changes what the
    next invoice costs and leaves every invoice already raised exactly as
    it was printed: those store their own rate per line.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "No such product.")

    changes = payload.model_dump(exclude_unset=True)
    if "hsn" in changes:
        _require_rate(db, changes["hsn"])
    for field, value in changes.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return ProductOut.model_validate(product).model_copy(
        update={"name": product.display_name}
    )


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """Remove a product, or retire it if it has history.

    A SKU that has never been bought or sold is deleted outright. One that
    appears on an invoice or in the stock ledger is deactivated instead:
    deleting it would orphan those rows and change what an old bill says.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "No such product.")

    sold = db.execute(
        select(func.count()).select_from(InvoiceLine).where(
            InvoiceLine.product_id == product_id
        )
    ).scalar_one()
    moved = db.execute(
        select(func.count()).select_from(StockLedger).where(
            StockLedger.product_id == product_id
        )
    ).scalar_one()

    if sold or moved:
        on_hand = stock.sellable_pieces(db, product_id, dt.date.today())
        product.is_active = False
        db.commit()
        return {
            "deleted": False,
            "deactivated": True,
            "invoice_lines": sold,
            "ledger_rows": moved,
            "on_hand_pieces": on_hand,
            "message": (
                f"{product.display_name} appears on {sold} invoice line(s) and "
                f"{moved} stock movement(s), so it has been retired instead of "
                "deleted. It will not appear on new bills; old ones are "
                "unchanged."
            ),
        }

    name = product.display_name
    db.delete(product)
    db.commit()
    return {
        "deleted": True,
        "deactivated": False,
        "message": f"{name} had no history and has been deleted.",
    }


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    if db.execute(
        select(Product).where(Product.sku_code == payload.sku_code)
    ).scalar_one_or_none():
        raise HTTPException(409, f"SKU {payload.sku_code} already exists.")
    _require_rate(db, payload.hsn)
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductOut.model_validate(product).model_copy(
        update={"name": product.display_name}
    )


@router.get("/brands", response_model=list[str])
def list_brands(db: Session = Depends(get_db)):
    return list(
        db.execute(select(Product.brand).distinct().order_by(Product.brand)).scalars()
    )


@router.get("/retailers", response_model=list[RetailerOut])
def list_retailers(
    search: str | None = None,
    route_id: int | None = None,
    party_type: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    stmt = select(Retailer)
    if active_only:
        stmt = stmt.where(Retailer.is_active)
    if route_id:
        stmt = stmt.where(Retailer.route_id == route_id)
    if party_type:
        stmt = stmt.where(Retailer.party_type == party_type)
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Retailer.shop_name.ilike(needle),
                Retailer.code.ilike(needle),
                Retailer.owner_name.ilike(needle),
                Retailer.phone.ilike(needle),
            )
        )
    retailers = db.execute(stmt.order_by(Retailer.shop_name)).scalars().all()
    return [_party_out(r) for r in retailers]


def _check_gstin_state(gstin: str | None, state_code: str | None) -> None:
    """A GSTIN's first two digits are the state code; they must agree.

    Catching this here matters because the state code decides CGST+SGST
    versus IGST, and a mismatch would tax the supply the wrong way round.
    """
    if gstin and state_code and gstin[:2] != state_code:
        raise HTTPException(
            422,
            f"GSTIN starts with {gstin[:2]} but the state code is "
            f"{state_code}; they must match.",
        )


def _party_out(retailer: Retailer) -> RetailerOut:
    return RetailerOut.model_validate(retailer).model_copy(
        update={"route_name": retailer.route.name if retailer.route else None}
    )


@router.post("/retailers", response_model=RetailerOut, status_code=201)
def create_retailer(payload: RetailerIn, db: Session = Depends(get_db)):
    """Add a party: a shop, or a sub-distributor.

    A GSTIN is optional. Most kirana shops are under the registration
    threshold, and a bill to one is an ordinary B2C supply that still
    carries GST and still reaches GSTR-1, in the B2CS table.
    """
    data = payload.model_dump()
    gstin = data.get("gstin")
    _check_gstin_state(gstin, data["state_code"])

    last = db.execute(select(func.max(Retailer.code))).scalar_one()
    next_num = (int(last[1:]) + 1) if last else 1
    retailer = Retailer(
        code=f"R{next_num:04d}", is_registered=bool(gstin), **data
    )
    db.add(retailer)
    db.commit()
    db.refresh(retailer)
    return _party_out(retailer)


@router.patch("/retailers/{retailer_id}", response_model=RetailerOut)
def update_retailer(
    retailer_id: int, payload: RetailerPatch, db: Session = Depends(get_db)
):
    """Edit a party. Only the fields actually sent are written."""
    retailer = db.get(Retailer, retailer_id)
    if retailer is None:
        raise HTTPException(404, "No such party.")

    changes = payload.model_dump(exclude_unset=True)
    _check_gstin_state(
        changes.get("gstin", retailer.gstin),
        changes.get("state_code", retailer.state_code),
    )
    for field, value in changes.items():
        setattr(retailer, field, value)
    if "gstin" in changes:
        retailer.is_registered = bool(changes["gstin"])

    db.commit()
    db.refresh(retailer)
    return _party_out(retailer)


@router.get("/routes", response_model=list[RouteOut])
def list_routes(db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(Retailer.route_id, func.count(Retailer.id))
            .where(Retailer.is_active)
            .group_by(Retailer.route_id)
        ).all()
    )
    routes = db.execute(select(Route).order_by(Route.day_of_week)).scalars().all()
    return [
        RouteOut.model_validate(b).model_copy(
            update={"retailer_count": counts.get(b.id, 0)}
        )
        for b in routes
    ]


@router.get("/gst-rates")
def list_gst_rates(db: Session = Depends(get_db)):
    rows = db.execute(
        select(GstRate).order_by(GstRate.hsn, GstRate.effective_from.desc())
    ).scalars()
    today = dt.date.today()
    return [
        {
            "id": r.id,
            "hsn": r.hsn,
            "rate": float(r.rate),
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
            "is_current": r.effective_from <= today
            and (r.effective_to is None or r.effective_to >= today),
            "note": r.note,
        }
        for r in rows
    ]
