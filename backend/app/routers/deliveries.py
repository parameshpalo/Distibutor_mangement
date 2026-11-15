"""Van runs. Thin over `services.deliveries`, which holds all the rules."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import DeliveryEdit, DeliveryIn, DeliveryStatusIn
from ..services import deliveries as service

router = APIRouter(prefix="/api/deliveries", tags=["deliveries"])


def _summary(db: Session, run):
    return service.run_summary(db, run)


@router.get("")
def list_runs(limit: int = 30, status: str | None = None, db: Session = Depends(get_db)):
    return service.list_runs(db, limit=limit, status=status)


# Declared before /{delivery_id} so "open" is not read as an id.
@router.get("/open")
def open_runs(on: dt.date | None = None, db: Session = Depends(get_db)):
    """The runs a new bill can be put on, for the billing screen's picker."""
    return [
        {
            "id": run.id,
            "delivery_no": run.delivery_no,
            "delivery_date": run.delivery_date,
            "status": run.status,
            "bill_count": len([b for b in run.bills if b.status != "cancelled"]),
        }
        for run in service.open_runs(db, on)
    ]


@router.post("", status_code=201)
def create_run(payload: DeliveryIn, db: Session = Depends(get_db)):
    try:
        run = service.create_run(
            db,
            run_date=payload.delivery_date,
            note=payload.note,
        )
    except service.DeliveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _summary(db, run)


@router.get("/{delivery_id}")
def get_run(delivery_id: int, db: Session = Depends(get_db)):
    try:
        return _summary(db, service._load(db, delivery_id))
    except service.DeliveryError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{delivery_id}/loading-list")
def loading_list(delivery_id: int, db: Session = Depends(get_db)):
    try:
        run = service._load(db, delivery_id)
    except service.DeliveryError as exc:
        raise HTTPException(404, str(exc)) from exc
    return service.loading_list(db, run)


@router.patch("/{delivery_id}")
def update_run(delivery_id: int, payload: DeliveryEdit, db: Session = Depends(get_db)):
    try:
        run = service.update_run(
            db,
            delivery_id,
            note=payload.note,
        )
    except service.DeliveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _summary(db, run)


@router.post("/{delivery_id}/status")
def set_status(
    delivery_id: int, payload: DeliveryStatusIn, db: Session = Depends(get_db)
):
    try:
        run = service.set_status(db, delivery_id=delivery_id, status=payload.status)
    except service.DeliveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _summary(db, run)


@router.post("/{delivery_id}/bills/{invoice_id}")
def add_bill(delivery_id: int, invoice_id: int, db: Session = Depends(get_db)):
    try:
        run = service.add_bill(db, delivery_id=delivery_id, invoice_id=invoice_id)
    except service.DeliveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _summary(db, run)


@router.delete("/{delivery_id}/bills/{invoice_id}")
def remove_bill(delivery_id: int, invoice_id: int, db: Session = Depends(get_db)):
    try:
        run = service.remove_bill(db, delivery_id=delivery_id, invoice_id=invoice_id)
    except service.DeliveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _summary(db, run)
