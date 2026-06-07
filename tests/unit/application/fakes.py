from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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


@dataclass
class InMemoryState:
    orders: dict[str, Order] = field(default_factory=dict)
    inventory: dict[str, InventoryItem] = field(default_factory=dict)
    shipments_by_order_id: dict[str, Shipment] = field(default_factory=dict)
    events: list[StoredEvent] = field(default_factory=list)
    idempotency: dict[str, IdempotencyRecord] = field(default_factory=dict)
    processed: set[tuple[str, str]] = field(default_factory=set)
    order_summary: OrderSummary = field(default_factory=OrderSummary)
    dead_letters: list[DeadLetterEvent] = field(default_factory=list)
    committed: int = 0


class FakeOrderRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def add(self, order: Order) -> None:
        self.state.orders[order.id] = order

    def get(self, order_id: str) -> Order | None:
        return self.state.orders.get(order_id)

    def get_for_update(self, order_id: str) -> Order | None:
        return self.get(order_id)

    def save(self, order: Order) -> None:
        self.state.orders[order.id] = order


class FakeInventoryRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def add(self, item: InventoryItem) -> None:
        self.state.inventory[item.sku] = item

    def get(self, sku: str) -> InventoryItem | None:
        return self.state.inventory.get(sku)

    def get_for_update(self, sku: str) -> InventoryItem | None:
        return self.get(sku)

    def save(self, item: InventoryItem) -> None:
        self.state.inventory[item.sku] = item


class FakeShipmentRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def add(self, shipment: Shipment) -> None:
        self.state.shipments_by_order_id[shipment.order_id] = shipment

    def get_by_order_id(self, order_id: str) -> Shipment | None:
        return self.state.shipments_by_order_id.get(order_id)


class FakeEventLogRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def append(self, event: DomainEvent) -> StoredEvent:
        stored = StoredEvent(
            id=len(self.state.events) + 1,
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )
        self.state.events.append(stored)
        return stored

    def get(self, event_id: str) -> StoredEvent | None:
        return next((event for event in self.state.events if event.event_id == event_id), None)

    def list_all(self) -> list[StoredEvent]:
        return list(self.state.events)

    def list_unpublished(self, limit: int) -> list[StoredEvent]:
        return [event for event in self.state.events if event.published_at is None][:limit]

    def mark_published(self, event_id: str) -> None:
        self.state.events = [
            StoredEvent(
                id=event.id,
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                payload=event.payload,
                occurred_at=event.occurred_at,
                published_at=datetime.now(timezone.utc)
                if event.event_id == event_id
                else event.published_at,
            )
            for event in self.state.events
        ]


class FakeIdempotencyRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def get(self, key: str) -> IdempotencyRecord | None:
        return self.state.idempotency.get(key)

    def save(self, key: str, payload_hash: str, response: dict[str, Any]) -> None:
        self.state.idempotency[key] = IdempotencyRecord(key, payload_hash, response)


class FakeProcessedEventRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def try_insert(self, consumer_name: str, event_id: str) -> bool:
        key = (consumer_name, event_id)
        if key in self.state.processed:
            return False
        self.state.processed.add(key)
        return True


class FakeOrderSummaryRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def get(self) -> OrderSummary:
        return self.state.order_summary

    def replace(self, summary: OrderSummary) -> None:
        self.state.order_summary = summary

    def increment(self, field_name: str, amount: int = 1) -> None:
        setattr(
            self.state.order_summary,
            field_name,
            getattr(self.state.order_summary, field_name) + amount,
        )


class FakeDeadLetterRepository:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state

    def add(
        self,
        consumer_name: str,
        event: StoredEvent,
        error: str,
        failures: int,
    ) -> DeadLetterEvent:
        dead_letter = DeadLetterEvent(
            id=len(self.state.dead_letters) + 1,
            consumer_name=consumer_name,
            event_id=event.event_id,
            event_type=event.event_type,
            payload=event.payload,
            error=error,
            failures=failures,
        )
        self.state.dead_letters.append(dead_letter)
        return dead_letter

    def get(self, dead_letter_id: int) -> DeadLetterEvent | None:
        return next((item for item in self.state.dead_letters if item.id == dead_letter_id), None)

    def mark_redriven(self, dead_letter_id: int) -> None:
        for item in self.state.dead_letters:
            if item.id == dead_letter_id:
                self.state.dead_letters.remove(item)
                self.state.dead_letters.append(
                    DeadLetterEvent(
                        id=item.id,
                        consumer_name=item.consumer_name,
                        event_id=item.event_id,
                        event_type=item.event_type,
                        payload=item.payload,
                        error=item.error,
                        failures=item.failures,
                        redriven_at=datetime.now(timezone.utc),
                    )
                )
                return


class FakeUnitOfWork:
    def __init__(self, state: InMemoryState) -> None:
        self.state = state
        self.orders = FakeOrderRepository(state)
        self.inventory = FakeInventoryRepository(state)
        self.shipments = FakeShipmentRepository(state)
        self.events = FakeEventLogRepository(state)
        self.idempotency = FakeIdempotencyRepository(state)
        self.processed_events = FakeProcessedEventRepository(state)
        self.order_summary = FakeOrderSummaryRepository(state)
        self.dead_letters = FakeDeadLetterRepository(state)

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def commit(self) -> None:
        self.state.committed += 1

    def rollback(self) -> None:
        return None


def fake_uow_factory(state: InMemoryState):
    return lambda: FakeUnitOfWork(state)

