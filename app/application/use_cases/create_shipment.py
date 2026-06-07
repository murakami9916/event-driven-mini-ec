from __future__ import annotations

from app.application.dto.models import HandlerResult, StoredEvent
from app.application.exceptions import NotFound
from app.application.ports.uow import UnitOfWorkFactory
from app.domain.events.models import DomainEvent, INVENTORY_RESERVED, SHIPMENT_CREATED
from app.domain.shipping.models import Shipment


class CreateShipmentUseCase:
    consumer_name = "shipping-worker"

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, event: StoredEvent) -> HandlerResult:
        if event.event_type != INVENTORY_RESERVED:
            return HandlerResult(handled=False, message="event ignored")

        with self._uow_factory() as uow:
            if not uow.processed_events.try_insert(self.consumer_name, event.event_id):
                return HandlerResult(handled=True, duplicate=True, message="duplicate event")

            order_id = str(event.payload["order_id"])
            order = uow.orders.get_for_update(order_id)
            if order is None:
                raise NotFound(f"order not found: {order_id}")

            existing = uow.shipments.get_by_order_id(order_id)
            if existing is not None:
                uow.commit()
                return HandlerResult(handled=True, duplicate=True, message="shipment already exists")

            shipment = Shipment.create_for_order(order_id)
            uow.shipments.add(shipment)
            order.mark_shipment_created()
            uow.orders.save(order)
            emitted = uow.events.append(
                DomainEvent(
                    event_type=SHIPMENT_CREATED,
                    aggregate_type="shipment",
                    aggregate_id=shipment.id,
                    payload={"shipment_id": shipment.id, "order_id": order_id},
                )
            )
            uow.commit()
            return HandlerResult(handled=True, emitted_event_id=emitted.event_id)

