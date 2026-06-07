from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.application.dto.models import CreateOrderCommand, InventoryAdjustmentCommand, OrderLineInput
from app.application.exceptions import IdempotencyConflict, NotFound
from app.application.use_cases.admin_events import RedriveDeadLetterUseCase, ReplayEventUseCase
from app.application.use_cases.adjust_inventory import AdjustInventoryUseCase
from app.application.use_cases.create_order import CreateOrderUseCase
from app.application.use_cases.get_inventory import GetInventoryUseCase
from app.application.use_cases.get_order import GetOrderUseCase
from app.application.use_cases.projections import GetOrderSummaryUseCase, RebuildOrderSummaryUseCase
from app.config import get_settings
from app.infrastructure.db.session import create_session_factory, init_database
from app.infrastructure.db.uow import SqlAlchemyUnitOfWork
from app.infrastructure.redis.publisher import RedisStreamPublisher
from app.infrastructure.toxiproxy.client import ToxiproxyClient
from app.interfaces.api.schemas import (
    CreateOrderRequest,
    InventoryAdjustmentRequest,
    InventoryResponse,
    OrderDetailsResponse,
    OrderResponse,
    OrderSummaryResponse,
    RedriveResponse,
    ReplayResponse,
)


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    session_factory = create_session_factory(settings.database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)
    publisher = RedisStreamPublisher(settings.redis_url, settings.event_stream)
    toxiproxy = ToxiproxyClient(settings.toxiproxy_url)

    app = FastAPI(title="Mini EC", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.on_event("startup")
    def startup() -> None:
        init_database(settings.database_url)

    @app.exception_handler(IdempotencyConflict)
    def idempotency_conflict_handler(_, exc: IdempotencyConflict):
        return _http_exception_response(409, str(exc))

    @app.exception_handler(NotFound)
    def not_found_handler(_, exc: NotFound):
        return _http_exception_response(404, str(exc))

    @app.exception_handler(ValueError)
    def value_error_handler(_, exc: ValueError):
        return _http_exception_response(400, str(exc))

    @app.exception_handler(SQLAlchemyError)
    def sqlalchemy_error_handler(_, exc: SQLAlchemyError):
        return _http_exception_response(503, f"database unavailable: {exc.__class__.__name__}")

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/orders", response_model=OrderResponse)
    def create_order(
        request: CreateOrderRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> OrderResponse:
        result = CreateOrderUseCase(uow_factory).execute(
            CreateOrderCommand(
                idempotency_key=idempotency_key,
                items=[
                    OrderLineInput(sku=item.sku, quantity=item.quantity)
                    for item in request.items
                ],
            )
        )
        return OrderResponse(order_id=result.order_id, status=result.status, items=result.items)

    @app.get("/orders/{order_id}", response_model=OrderDetailsResponse)
    def get_order(order_id: str) -> OrderDetailsResponse:
        details = GetOrderUseCase(uow_factory).execute(order_id)
        return OrderDetailsResponse(
            order_id=details.order_id,
            status=str(details.status),
            items=details.items,
            shipment=details.shipment,
        )

    @app.post("/inventory/adjustments", response_model=InventoryResponse)
    def adjust_inventory(request: InventoryAdjustmentRequest) -> InventoryResponse:
        result = AdjustInventoryUseCase(uow_factory).execute(
            InventoryAdjustmentCommand(sku=request.sku, delta=request.delta)
        )
        return InventoryResponse(
            sku=result.sku,
            on_hand=result.on_hand,
            reserved=result.reserved,
            available=result.available,
        )

    @app.get("/inventory/{sku}", response_model=InventoryResponse)
    def get_inventory(sku: str) -> InventoryResponse:
        result = GetInventoryUseCase(uow_factory).execute(sku)
        return InventoryResponse(
            sku=result.sku,
            on_hand=result.on_hand,
            reserved=result.reserved,
            available=result.available,
        )

    @app.get("/read-models/order-summary", response_model=OrderSummaryResponse)
    def get_order_summary() -> OrderSummaryResponse:
        summary = GetOrderSummaryUseCase(uow_factory).execute()
        return OrderSummaryResponse(**summary.as_dict())

    @app.post(
        "/admin/projections/order-summary/rebuild",
        response_model=OrderSummaryResponse,
    )
    def rebuild_order_summary() -> OrderSummaryResponse:
        summary = RebuildOrderSummaryUseCase(uow_factory).execute()
        return OrderSummaryResponse(**summary.as_dict())

    @app.post("/admin/events/{event_id}/replay", response_model=ReplayResponse)
    def replay_event(event_id: str) -> ReplayResponse:
        result = ReplayEventUseCase(uow_factory, publisher).execute(event_id)
        return ReplayResponse(**result)

    @app.post("/admin/dlq/{dead_letter_id}/redrive", response_model=RedriveResponse)
    def redrive_dead_letter(dead_letter_id: int) -> RedriveResponse:
        result = RedriveDeadLetterUseCase(uow_factory, publisher).execute(dead_letter_id)
        return RedriveResponse(**result)

    @app.post("/admin/faults/{target}/{action}")
    def set_fault(target: str, action: str) -> dict[str, object]:
        if target not in {"postgres", "redis"}:
            raise HTTPException(status_code=400, detail="target must be postgres or redis")
        if action in {"cut", "down", "disable"}:
            enabled = False
        elif action in {"restore", "up", "enable"}:
            enabled = True
        else:
            raise HTTPException(status_code=400, detail="action must be cut or restore")
        return toxiproxy.set_enabled(target, enabled)

    return app


def _http_exception_response(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})

