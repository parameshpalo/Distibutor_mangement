"""GST compliance: the GSTR-1 return.

Only GSTR-1 lives here. E-invoicing applies above a turnover threshold this
firm is well under, and e-way bills are raised on the government portal by
whoever is loading the van -- so neither is modelled in this app. A van load
over the consignment threshold still legally needs an e-way bill; it just
does not happen here.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import gstr1

router = APIRouter(prefix="/api/gst", tags=["compliance"])

SECTIONS = ("b2b", "b2cl", "b2cs", "cdnr", "hsn", "docs")


# --- GSTR-1 ----------------------------------------------------------------


@router.get("/gstr1")
def gstr1_summary(
    year: int = Query(..., ge=2017, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """What the return will contain, with the pre-filing checks."""
    return gstr1.build_summary(db, year, month)


@router.get("/gstr1/json")
def gstr1_json(
    year: int = Query(..., ge=2017, le=2100),
    month: int = Query(..., ge=1, le=12),
    download: bool = False,
    db: Session = Depends(get_db),
):
    """The return in the offline utility's JSON shape."""
    payload = gstr1.build_json(db, year, month)
    body = json.dumps(payload, indent=2, default=str)
    headers = {}
    if download:
        name = f"GSTR1_{payload['gstin']}_{payload['fp']}.json"
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/gstr1/csv")
def gstr1_csv(
    year: int = Query(..., ge=2017, le=2100),
    month: int = Query(..., ge=1, le=12),
    section: str = Query(default="b2b"),
    db: Session = Depends(get_db),
):
    """One section as CSV, laid out like the offline tool's sheets."""
    if section.lower() not in SECTIONS:
        raise HTTPException(
            422, f"Section must be one of: {', '.join(SECTIONS)}."
        )
    body = gstr1.build_csv(db, year, month, section)
    name = f"GSTR1_{section.upper()}_{month:02d}{year}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
