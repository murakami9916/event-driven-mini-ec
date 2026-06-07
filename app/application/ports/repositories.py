from __future__ import annotations

from typing import Any, Protocol

from app.application.dto.models import (
    DeadLetterEvent,
    IdempotencyRecord,
    OrderSummary,
    StoredEvent,
)
from app.domain.events.models import DomainEvent
from app.domain.inventory.models import InventoryItem
from app.domain.orders.models import Order
from app.domain.shipping.models import Shipment


class OrderRepository(Protocol):
    def add(self, order: Order) -> None: ...

    def get(self, order_id: str) -> Order | None: ...

    def get_for_update(self, order_id: str) -> Order | None: ...

    def save(self, order: Order) -> None: ...


class InventoryRepository(Protocol):
    def add(self, item: InventoryItem) -> None: ...

    def get(self, sku: str) -> InventoryItem | None: ...

    def get_for_update(self, sku: str) -> InventoryItem | None: ...

    def save(self, item: InventoryItem) -> None: ...


class ShipmentRepository(Protocol):
    def add(self, shipment: Shipment) -> None: ...

    def get_by_order_id(self, order_id: str) -> Shipment | None: ...


class EventLogRepository(Protocol):
    def append(self, event: DomainEvent) -> StoredEvent: ...

    def get(self, event_id: str) -> StoredEvent | None: ...

    def list_all(self) -> list[StoredEvent]: ...

    def list_unpublished(self, limit: int) -> list[StoredEvent]: ...

    def mark_published(self, event_id: str) -> None: ...


class IdempotencyRepository(Protocol):
    def get(self, key: str) -> IdempotencyRecord | None: ...

    def save(self, key: str, payload_hash: str, response: dict[str, Any]) -> None: ...


class ProcessedEventRepository(Protocol):
    def try_insert(self, consumer_name: str, event_id: str) -> bool: ...


class OrderSummaryRepository(Protocol):
    def get(self) -> OrderSummary: ...

    def replace(self, summary: OrderSummary) -> None: ...

    def increment(self, field_name: str, amount: int = 1) -> None: ...


class DeadLetterRepository(Protocol):
    def add(
        self,
        consumer_name: str,
        event: StoredEvent,
        error: str,
        failures: int,
    ) -> DeadLetterEvent: ...

    def get(self, dead_letter_id: int) -> DeadLetterEvent | None: ...

    def mark_redriven(self, dead_letter_id: int) -> None: ...

