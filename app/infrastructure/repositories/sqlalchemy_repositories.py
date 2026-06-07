from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.dto.models import (
    DeadLetterEvent,
    IdempotencyRecord,
    OrderSummary,
    StoredEvent,
)
from app.domain.events.models import DomainEvent
from app.domain.inventory.models import InventoryItem
from app.domain.orders.models import Order, OrderItem, OrderStatus
from app.domain.shipping.models import Shipment, ShipmentStatus
from app.infrastructure.db.models import (
    DeadLetterEventModel,
    EventLogModel,
    IdempotencyKeyModel,
    InventoryItemModel,
    OrderItemModel,
    OrderModel,
    OrderSummaryReadModel,
    ProcessedEventModel,
    ShipmentModel,
    utcnow,
)


def _to_stored_event(model: EventLogModel) -> StoredEvent:
    return StoredEvent(
        id=model.id,
        event_id=model.event_id,
        event_type=model.event_type,
        aggregate_type=model.aggregate_type,
        aggregate_id=model.aggregate_id,
        payload=dict(model.payload),
        occurred_at=model.occurred_at,
        published_at=model.published_at,
    )


def _to_order(model: OrderModel) -> Order:
    return Order(
        id=model.id,
        status=OrderStatus(model.status),
        items=[OrderItem(sku=item.sku, quantity=item.quantity) for item in model.items],
    )


def _to_inventory_item(model: InventoryItemModel) -> InventoryItem:
    return InventoryItem(sku=model.sku, on_hand=model.on_hand, reserved=model.reserved)


def _to_shipment(model: ShipmentModel) -> Shipment:
    return Shipment(
        id=model.id,
        order_id=model.order_id,
        status=ShipmentStatus(model.status),
    )


class SqlAlchemyOrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, order: Order) -> None:
        self.session.add(
            OrderModel(
                id=order.id,
                status=str(order.status),
                items=[
                    OrderItemModel(sku=item.sku, quantity=item.quantity)
                    for item in order.items
                ],
            )
        )

    def get(self, order_id: str) -> Order | None:
        model = self.session.get(OrderModel, order_id)
        return None if model is None else _to_order(model)

    def get_for_update(self, order_id: str) -> Order | None:
        model = self.session.get(OrderModel, order_id, with_for_update=True)
        return None if model is None else _to_order(model)

    def save(self, order: Order) -> None:
        model = self.session.get(OrderModel, order.id, with_for_update=True)
        if model is None:
            self.add(order)
            return
        model.status = str(order.status)


class SqlAlchemyInventoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: InventoryItem) -> None:
        self.session.add(
            InventoryItemModel(
                sku=item.sku,
                on_hand=item.on_hand,
                reserved=item.reserved,
            )
        )

    def get(self, sku: str) -> InventoryItem | None:
        model = self.session.get(InventoryItemModel, sku)
        return None if model is None else _to_inventory_item(model)

    def get_for_update(self, sku: str) -> InventoryItem | None:
        model = self.session.get(InventoryItemModel, sku, with_for_update=True)
        return None if model is None else _to_inventory_item(model)

    def save(self, item: InventoryItem) -> None:
        model = self.session.get(InventoryItemModel, item.sku, with_for_update=True)
        if model is None:
            self.add(item)
            return
        model.on_hand = item.on_hand
        model.reserved = item.reserved


class SqlAlchemyShipmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, shipment: Shipment) -> None:
        self.session.add(
            ShipmentModel(
                id=shipment.id,
                order_id=shipment.order_id,
                status=str(shipment.status),
            )
        )

    def get_by_order_id(self, order_id: str) -> Shipment | None:
        model = self.session.scalar(
            select(ShipmentModel).where(ShipmentModel.order_id == order_id)
        )
        return None if model is None else _to_shipment(model)


class SqlAlchemyEventLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, event: DomainEvent) -> StoredEvent:
        model = EventLogModel(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )
        self.session.add(model)
        self.session.flush()
        return _to_stored_event(model)

    def get(self, event_id: str) -> StoredEvent | None:
        model = self.session.scalar(select(EventLogModel).where(EventLogModel.event_id == event_id))
        return None if model is None else _to_stored_event(model)

    def list_all(self) -> list[StoredEvent]:
        models = self.session.scalars(select(EventLogModel).order_by(EventLogModel.id)).all()
        return [_to_stored_event(model) for model in models]

    def list_unpublished(self, limit: int) -> list[StoredEvent]:
        models = self.session.scalars(
            select(EventLogModel)
            .where(EventLogModel.published_at.is_(None))
            .order_by(EventLogModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        return [_to_stored_event(model) for model in models]

    def mark_published(self, event_id: str) -> None:
        model = self.session.scalar(select(EventLogModel).where(EventLogModel.event_id == event_id))
        if model is None:
            return
        model.published_at = datetime.now(timezone.utc)
        model.publish_attempts += 1


class SqlAlchemyIdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str) -> IdempotencyRecord | None:
        model = self.session.get(IdempotencyKeyModel, key)
        if model is None:
            return None
        return IdempotencyRecord(
            key=model.key,
            payload_hash=model.payload_hash,
            response=dict(model.response),
        )

    def save(self, key: str, payload_hash: str, response: dict[str, Any]) -> None:
        self.session.add(
            IdempotencyKeyModel(
                key=key,
                payload_hash=payload_hash,
                response=response,
            )
        )


class SqlAlchemyProcessedEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def try_insert(self, consumer_name: str, event_id: str) -> bool:
        self.session.add(ProcessedEventModel(consumer_name=consumer_name, event_id=event_id))
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            return False
        return True


class SqlAlchemyOrderSummaryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _get_or_create_model(self) -> OrderSummaryReadModel:
        model = self.session.get(OrderSummaryReadModel, 1, with_for_update=True)
        if model is None:
            model = OrderSummaryReadModel(id=1)
            self.session.add(model)
            self.session.flush()
        return model

    def get(self) -> OrderSummary:
        model = self._get_or_create_model()
        return OrderSummary(
            orders_created=model.orders_created,
            inventory_reserved=model.inventory_reserved,
            inventory_rejected=model.inventory_rejected,
            shipments_created=model.shipments_created,
        )

    def replace(self, summary: OrderSummary) -> None:
        model = self._get_or_create_model()
        model.orders_created = summary.orders_created
        model.inventory_reserved = summary.inventory_reserved
        model.inventory_rejected = summary.inventory_rejected
        model.shipments_created = summary.shipments_created

    def increment(self, field_name: str, amount: int = 1) -> None:
        model = self._get_or_create_model()
        setattr(model, field_name, getattr(model, field_name) + amount)


class SqlAlchemyDeadLetterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        consumer_name: str,
        event: StoredEvent,
        error: str,
        failures: int,
    ) -> DeadLetterEvent:
        model = DeadLetterEventModel(
            consumer_name=consumer_name,
            event_id=event.event_id,
            event_type=event.event_type,
            payload=event.payload,
            error=error,
            failures=failures,
        )
        self.session.add(model)
        self.session.flush()
        return DeadLetterEvent(
            id=model.id,
            consumer_name=model.consumer_name,
            event_id=model.event_id,
            event_type=model.event_type,
            payload=dict(model.payload),
            error=model.error,
            failures=model.failures,
            redriven_at=model.redriven_at,
        )

    def get(self, dead_letter_id: int) -> DeadLetterEvent | None:
        model = self.session.get(DeadLetterEventModel, dead_letter_id)
        if model is None:
            return None
        return DeadLetterEvent(
            id=model.id,
            consumer_name=model.consumer_name,
            event_id=model.event_id,
            event_type=model.event_type,
            payload=dict(model.payload),
            error=model.error,
            failures=model.failures,
            redriven_at=model.redriven_at,
        )

    def mark_redriven(self, dead_letter_id: int) -> None:
        model = self.session.get(DeadLetterEventModel, dead_letter_id)
        if model is not None:
            model.redriven_at = utcnow()

