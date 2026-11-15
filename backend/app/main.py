"""Application entry point."""

import datetime as dt
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import decode_token
from .config import get_settings
from .database import Base, engine
from .routers import (
    auth,
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

# Public endpoints that do not need a bearer token.
_PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in _PUBLIC_PATHS:
            return await call_next(request)
        if path.startswith("/api/"):
            header = request.headers.get("authorization", "")
            if not header.lower().startswith("bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                request.state.username = decode_token(header.split(" ", 1)[1].strip())
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)


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

app.add_middleware(AuthMiddleware)
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


app.include_router(auth.router)
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
