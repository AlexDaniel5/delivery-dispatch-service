"""FastAPI application wiring: routes, middleware, WebSocket and metrics."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
)
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.auth import require_api_key
from app.config import get_settings
from app.database import get_session, init_db
from app.dispatch import (
    CourierBusyError,
    DispatchService,
    OrderNotFoundError,
    get_order_or_raise,
)
from app.events import event_bus
from app.logging_config import configure_logging, get_logger, request_id_var
from app.metrics import registry
from app.models import Courier, Order
from app.schemas import (
    CourierCreate,
    CourierRead,
    CourierUpdate,
    OrderCreate,
    OrderRead,
    OrderStatusUpdate,
    Page,
)
from app.state_machine import CourierStatus, InvalidTransitionError, OrderStatus

logger = get_logger("api")


def get_dispatch() -> DispatchService:
    """FastAPI dependency returning a dispatch service."""
    return DispatchService()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise logging, DB and the event bus loop binding on startup."""
    configure_logging()
    if get_settings().auto_create_tables:
        init_db()
    event_bus.bind_loop(asyncio.get_running_loop())
    logger.info("service started")
    yield
    logger.info("service stopped")


app = FastAPI(title="Delivery Dispatch Service", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a request ID and emit a structured access log line."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_var.set(request_id)
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    if get_settings().request_logging:
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
    request_id_var.reset(token)
    return response


@app.exception_handler(InvalidTransitionError)
async def invalid_transition_handler(request: Request, exc: InvalidTransitionError) -> JSONResponse:
    """Return 409 for state-machine violations."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(OrderNotFoundError)
async def order_not_found_handler(request: Request, exc: OrderNotFoundError) -> JSONResponse:
    """Return 404 for unknown orders."""
    return JSONResponse(status_code=404, content={"detail": f"order {exc} not found"})


@app.exception_handler(CourierBusyError)
async def courier_busy_handler(request: Request, exc: CourierBusyError) -> JSONResponse:
    """Return 409 when changing a busy courier's availability."""
    return JSONResponse(
        status_code=409,
        content={"detail": "cannot change availability of a busy courier"},
    )


# -- health & metrics ------------------------------------------------------


@app.get("/")
def index() -> dict[str, object]:
    """Service index with pointers to the main endpoints."""
    return {
        "service": "delivery-dispatch-service",
        "version": app.version,
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "metrics": "/metrics",
            "couriers": "/couriers",
            "orders": "/orders",
            "orders_ws": "/ws/orders",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


# -- couriers --------------------------------------------------------------


@app.post(
    "/couriers",
    response_model=CourierRead,
    status_code=201,
    dependencies=[Depends(require_api_key)],
)
def create_courier(
    payload: CourierCreate,
    session: Session = Depends(get_session),
    dispatch: DispatchService = Depends(get_dispatch),
) -> Courier:
    """Register a courier (available by default) and drain the queue."""
    courier = Courier(
        id=str(uuid.uuid4()),
        name=payload.name,
        lat=payload.lat,
        lon=payload.lon,
    )
    session.add(courier)
    session.commit()
    session.refresh(courier)
    dispatch.process_queue(session)
    session.refresh(courier)
    return courier


@app.get("/couriers", response_model=Page[CourierRead])
def list_couriers(
    session: Session = Depends(get_session),
    status: CourierStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[CourierRead]:
    """List couriers, optionally filtered by status, with pagination."""
    filters = [Courier.status == status] if status is not None else []
    total = session.scalar(select(func.count()).select_from(Courier).where(*filters)) or 0
    rows = (
        session.execute(
            select(Courier)
            .where(*filters)
            .order_by(Courier.created_at.asc(), Courier.id.asc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return Page[CourierRead](
        items=[CourierRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/couriers/{courier_id}", response_model=CourierRead)
def get_courier(courier_id: str, session: Session = Depends(get_session)) -> Courier:
    """Fetch a courier by id."""
    courier = session.get(Courier, courier_id)
    if courier is None:
        raise HTTPException(status_code=404, detail="courier not found")
    return courier


@app.patch(
    "/couriers/{courier_id}",
    response_model=CourierRead,
    dependencies=[Depends(require_api_key)],
)
def update_courier(
    courier_id: str,
    payload: CourierUpdate,
    session: Session = Depends(get_session),
    dispatch: DispatchService = Depends(get_dispatch),
) -> Courier:
    """Update a courier's location and/or availability (drains the queue)."""
    courier = session.get(Courier, courier_id)
    if courier is None:
        raise HTTPException(status_code=404, detail="courier not found")
    return dispatch.update_courier(
        session, courier, lat=payload.lat, lon=payload.lon, status=payload.status
    )


# -- orders ----------------------------------------------------------------


@app.post("/orders", response_model=OrderRead, dependencies=[Depends(require_api_key)])
def create_order(
    payload: OrderCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    dispatch: DispatchService = Depends(get_dispatch),
) -> OrderRead:
    """Create and dispatch an order.

    Supply an ``Idempotency-Key`` header so a retried POST returns the original
    order instead of creating a duplicate.
    """
    order, created = dispatch.create_order(session, payload, idempotency_key)
    response.status_code = 201 if created else 200
    return OrderRead.model_validate(order)


@app.get("/orders", response_model=Page[OrderRead])
def list_orders(
    session: Session = Depends(get_session),
    status: OrderStatus | None = Query(default=None),
    courier_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[OrderRead]:
    """List orders, optionally filtered by status and/or courier, paginated."""
    filters = []
    if status is not None:
        filters.append(Order.status == status)
    if courier_id is not None:
        filters.append(Order.courier_id == courier_id)
    total = session.scalar(select(func.count()).select_from(Order).where(*filters)) or 0
    rows = (
        session.execute(
            select(Order)
            .where(*filters)
            .order_by(Order.created_at.desc(), Order.id.asc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return Page[OrderRead](
        items=[OrderRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/orders/{order_id}", response_model=OrderRead)
def get_order(order_id: str, session: Session = Depends(get_session)) -> OrderRead:
    """Fetch an order by id."""
    order = get_order_or_raise(session, order_id)
    return OrderRead.model_validate(order)


@app.post(
    "/orders/{order_id}/status",
    response_model=OrderRead,
    dependencies=[Depends(require_api_key)],
)
def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    session: Session = Depends(get_session),
    dispatch: DispatchService = Depends(get_dispatch),
) -> OrderRead:
    """Advance an order to a new status (state-machine enforced)."""
    order = get_order_or_raise(session, order_id)
    order = dispatch.advance_order(session, order, payload.status)
    return OrderRead.model_validate(order)


# -- websocket -------------------------------------------------------------


@app.websocket("/ws/orders")
async def orders_ws(websocket: WebSocket) -> None:
    """Stream order status change events to the client as JSON."""
    await websocket.accept()
    queue = event_bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)
