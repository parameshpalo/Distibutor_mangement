"""Application entry point."""

import datetime as dt
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .database import Base, engine
from .routers import (
    deliveries,
    billing,
    collections,
    compliance,
    dashboard,
    field_ops,
    inventory,
    masters,
)
from .services.stock import InsufficientStock

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Phase 1 creates the schema directly. Introduce Alembic before the
    # first production deployment, so later changes can migrate data.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Biscuit Distribution",
    description=(
        "Inventory, GST invoicing, collections and targets for a biscuit "
        "distributorship."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(InsufficientStock)
async def _insufficient_stock(_request: Request, exc: InsufficientStock):
    """Stock shortfalls are an everyday billing event, not a server fault."""
    return JSONResponse(
        status_code=409,
        content={
            "error": "insufficient_stock",
            "message": str(exc),
            "product": exc.label,
            "asked": exc.asked,
            "available": exc.available,
        },
    )


app.include_router(masters.router)
app.include_router(deliveries.router)
app.include_router(inventory.router)
app.include_router(billing.router)
app.include_router(collections.router)
app.include_router(field_ops.router)
app.include_router(compliance.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "server_date": dt.date.today()}
