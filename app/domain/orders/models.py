from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.events.models import DomainEvent, ORDER_CREATED


class OrderStatus(StrEnum):
    CREATED = "created"
    INVENTORY_RESERVED = "inventory_reserved"
    INVENTORY_REJECTED = "inventory_rejected"
    SHIPMENT_CREATED = "shipment_created"


@dataclass(frozen=True)
class OrderItem:
    sku: str
    quantity: int

    def __post_init__(self) -> None:
        if not self.sku.strip():
            raise ValueError("sku is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass
class Order:
    id: str
    items: list[OrderItem]
    status: OrderStatus = OrderStatus.CREATED

    @classmethod
    def create(cls, order_id: str, items: list[OrderItem]) -> "Order":
        if not order_id.strip():
            raise ValueError("order_id is required")
        if not items:
            raise ValueError("order must contain at least one item")
        return cls(id=order_id, items=list(items), status=OrderStatus.CREATED)

    def mark_inventory_reserved(self) -> None:
        if self.status == OrderStatus.INVENTORY_RESERVED:
            return
        if self.status != OrderStatus.CREATED:
            raise ValueError("inventory can only be reserved for newly created orders")
        self.status = OrderStatus.INVENTORY_RESERVED

    def mark_inventory_rejected(self) -> None:
        if self.status == OrderStatus.INVENTORY_REJECTED:
            return
        if self.status != OrderStatus.CREATED:
            raise ValueError("inventory can only be rejected for newly created orders")
        self.status = OrderStatus.INVENTORY_REJECTED

    def mark_shipment_created(self) -> None:
        if self.status == OrderStatus.SHIPMENT_CREATED:
            return
        if self.status != OrderStatus.INVENTORY_RESERVED:
            raise ValueError("shipment can only be created after inventory reservation")
        self.status = OrderStatus.SHIPMENT_CREATED

    def to_created_event(self) -> DomainEvent:
        return DomainEvent(
            event_type=ORDER_CREATED,
            aggregate_type="order",
            aggregate_id=self.id,
            payload={
                "order_id": self.id,
                "items": [{"sku": item.sku, "quantity": item.quantity} for item in self.items],
            },
        )

