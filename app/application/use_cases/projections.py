from __future__ import annotations

from app.application.dto.models import HandlerResult, OrderSummary, StoredEvent
from app.application.ports.uow import UnitOfWorkFactory
from app.domain.events.models import (
    INVENTORY_REJECTED,
    INVENTORY_RESERVED,
    ORDER_CREATED,
    SHIPMENT_CREATED,
)


SUMMARY_FIELDS = {
    ORDER_CREATED: "orders_created",
    INVENTORY_RESERVED: "inventory_reserved",
    INVENTORY_REJECTED: "inventory_rejected",
    SHIPMENT_CREATED: "shipments_created",
}


def apply_event_to_summary(summary: OrderSummary, event: StoredEvent) -> None:
    field_name = SUMMARY_FIELDS.get(event.event_type)
    if field_name is not None:
        setattr(summary, field_name, getattr(summary, field_name) + 1)


class ApplyOrderSummaryProjectionUseCase:
    consumer_name = "projection-worker"

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, event: StoredEvent) -> HandlerResult:
        field_name = SUMMARY_FIELDS.get(event.event_type)
        if field_name is None:
            return HandlerResult(handled=False, message="event ignored")

        with self._uow_factory() as uow:
            if not uow.processed_events.try_insert(self.consumer_name, event.event_id):
                return HandlerResult(handled=True, duplicate=True, message="duplicate event")
            uow.order_summary.increment(field_name)
            uow.commit()
            return HandlerResult(handled=True)


class RebuildOrderSummaryUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self) -> OrderSummary:
        with self._uow_factory() as uow:
            summary = OrderSummary()
            for event in uow.events.list_all():
                apply_event_to_summary(summary, event)
            uow.order_summary.replace(summary)
            uow.commit()
            return summary


class GetOrderSummaryUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self) -> OrderSummary:
        with self._uow_factory() as uow:
            return uow.order_summary.get()

