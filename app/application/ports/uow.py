from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.application.ports.repositories import (
    DeadLetterRepository,
    EventLogRepository,
    IdempotencyRepository,
    InventoryRepository,
    OrderRepository,
    OrderSummaryRepository,
    ProcessedEventRepository,
    ShipmentRepository,
)


class UnitOfWork(Protocol):
    orders: OrderRepository
    inventory: InventoryRepository
    shipments: ShipmentRepository
    events: EventLogRepository
    idempotency: IdempotencyRepository
    processed_events: ProcessedEventRepository
    order_summary: OrderSummaryRepository
    dead_letters: DeadLetterRepository

    def __enter__(self) -> "UnitOfWork": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]

