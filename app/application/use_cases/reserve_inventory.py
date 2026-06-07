from __future__ import annotations

from app.application.dto.models import HandlerResult, StoredEvent
from app.application.exceptions import NotFound
from app.application.ports.uow import UnitOfWorkFactory
from app.domain.events.models import DomainEvent, INVENTORY_REJECTED, INVENTORY_RESERVED, ORDER_CREATED
from app.domain.inventory.models import InventoryItem


class ReserveInventoryUseCase:
    consumer_name = "inventory-worker"

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, event: StoredEvent) -> HandlerResult:
        if event.event_type != ORDER_CREATED:
            return HandlerResult(handled=False, message="event ignored")

        with self._uow_factory() as uow:
            if not uow.processed_events.try_insert(self.consumer_name, event.event_id):
                return HandlerResult(handled=True, duplicate=True, message="duplicate event")

            order_id = str(event.payload["order_id"])
            order = uow.orders.get_for_update(order_id)
            if order is None:
                raise NotFound(f"order not found: {order_id}")

            lines = [
                {"sku": str(item["sku"]), "quantity": int(item["quantity"])}
                for item in event.payload["items"]
            ]
            inventory_items: dict[str, InventoryItem] = {}
            shortages: list[dict[str, int | str]] = []

            for line in lines:
                item = uow.inventory.get_for_update(str(line["sku"]))
                if item is None:
                    item = InventoryItem(sku=str(line["sku"]))
                    uow.inventory.add(item)
                inventory_items[item.sku] = item
                requested = int(line["quantity"])
                if item.available < requested:
                    shortages.append(
                        {
                            "sku": item.sku,
                            "requested": requested,
                            "available": item.available,
                        }
                    )

            if shortages:
                order.mark_inventory_rejected()
                emitted = uow.events.append(
                    DomainEvent(
                        event_type=INVENTORY_REJECTED,
                        aggregate_type="order",
                        aggregate_id=order.id,
                        payload={"order_id": order.id, "shortages": shortages},
                    )
                )
            else:
                for line in lines:
                    item = inventory_items[str(line["sku"])]
                    item.reserve(int(line["quantity"]))
                    uow.inventory.save(item)
                order.mark_inventory_reserved()
                emitted = uow.events.append(
                    DomainEvent(
                        event_type=INVENTORY_RESERVED,
                        aggregate_type="order",
                        aggregate_id=order.id,
                        payload={"order_id": order.id, "items": lines},
                    )
                )

            uow.orders.save(order)
            uow.commit()
            return HandlerResult(handled=True, emitted_event_id=emitted.event_id)

