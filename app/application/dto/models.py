from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.orders.models import OrderStatus
from app.domain.shipping.models import ShipmentStatus


@dataclass(frozen=True)
class OrderLineInput:
    sku: str
    quantity: int


@dataclass(frozen=True)
class CreateOrderCommand:
    idempotency_key: str
    items: list[OrderLineInput]


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str
    items: list[dict[str, Any]]


@dataclass(frozen=True)
class OrderDetails:
    order_id: str
    status: OrderStatus
    items: list[dict[str, Any]]
    shipment: dict[str, Any] | None = None


@dataclass(frozen=True)
class InventoryAdjustmentCommand:
    sku: str
    delta: int


@dataclass(frozen=True)
class InventoryResult:
    sku: str
    on_hand: int
    reserved: int
    available: int


@dataclass(frozen=True)
class ShipmentResult:
    shipment_id: str
    order_id: str
    status: ShipmentStatus


@dataclass(frozen=True)
class StoredEvent:
    id: int
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    occurred_at: datetime
    published_at: datetime | None = None


@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    payload_hash: str
    response: dict[str, Any]


@dataclass
class OrderSummary:
    orders_created: int = 0
    inventory_reserved: int = 0
    inventory_rejected: int = 0
    shipments_created: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "orders_created": self.orders_created,
            "inventory_reserved": self.inventory_reserved,
            "inventory_rejected": self.inventory_rejected,
            "shipments_created": self.shipments_created,
        }


@dataclass(frozen=True)
class HandlerResult:
    handled: bool
    duplicate: bool = False
    emitted_event_id: str | None = None
    message: str = ""


@dataclass(frozen=True)
class DeadLetterEvent:
    id: int
    consumer_name: str
    event_id: str
    event_type: str
    payload: dict[str, Any]
    error: str
    failures: int
    redriven_at: datetime | None = None


@dataclass
class EventHandlingFailure:
    failures: int = 0
    last_error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

